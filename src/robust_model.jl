# Robust capacitated facility location model (README2.md, Section 3.2).
#
#   include("src/robust_model.jl")
#   inst = load_instance(1000)
#   res  = solve_robust(inst, Params(delta = 1000, K = 10, gamma = 26))
#
# Demand points are census blocks (demand_blocks.csv). Uncertainty is per BLOCK GROUP
# (blockgroup_demand.csv): z_g in [0, 1], sum_g z_g <= gamma, and block i in group g gets
#     h_i = hhat_i + share_i * m_g * z_g
# because the ACS margin m_g belongs to the whole block group, not to any block.
#
# Algorithm: scenario generation (cutting planes, L14). The master MILP holds one copy of
# constraints (1)-(4), (7) per demand scenario, linked by (8) t >= cost_k. The adversary
# fixes the build decisions and finds a bad scenario by dual-based local search.

using JuMP, Gurobi, CSV, DataFrames, Printf

const DATA_DIR = normpath(joinpath(@__DIR__, "..", "data", "processed"))
const _GRB_ENV = Ref{Union{Nothing,Gurobi.Env}}(nothing)
function grb_env()
    _GRB_ENV[] === nothing && (_GRB_ENV[] = Gurobi.Env())
    return _GRB_ENV[]
end

Base.@kwdef struct Params
    delta::Int = 500                       # candidate grid spacing (m)
    K::Int = 10                            # max new pantries, countywide
    J_MAX::Union{Int,Nothing} = 2          # max pantries (existing + new) per block group; nothing = no cap
    N_NEW::Union{Int,Nothing} = 2          # max NEW pantries per block group; nothing = no cap
    c_exist::Float64 = 900.0               # capacity of an existing pantry (people/month)
    c_new::Float64 = 900.0                 # capacity of a new pantry (people/month)
    gamma::Float64 = 26.0                  # uncertainty budget (block groups at their margin)
    q::Float64 = 5000.0                    # penalty per unserved person (m)
    dmax::Float64 = 3000.0                 # reach limit (m)
    demand::String = "h_pov185"            # "h_pov185" or "h_pov100"
    mip_gap::Float64 = 0.005               # Gurobi MIPGap for each master solve
    time_limit::Float64 = 3600.0           # seconds per master solve
    tol::Float64 = 1e-4                    # stop when adversary cost <= t* (1 + tol)
    max_rounds::Int = 20
    tighten::Bool = true                   # include constraint (4)
    threads::Int = 0                       # 0 = Gurobi default
    verbose::Bool = false
end

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
struct Instance
    delta::Int
    dmax::Float64
    demand::String
    nI::Int                     # demand points (blocks)
    nE::Int                     # existing pantries: sites 1:nE
    nC::Int                     # candidate sites: sites nE+1 : nE+nC
    blk_id::Vector{String}
    blk_x::Vector{Float64}
    blk_y::Vector{Float64}
    hhat::Vector{Float64}       # block nominal demand
    dev::Vector{Float64}        # block demand increase when its group is at its margin: share_i * m_g
    g_of_i::Vector{Int}         # block -> block-group index
    bg_geoid::Vector{String}
    bg_hhat::Vector{Float64}
    bg_moe::Vector{Float64}
    blocks_of_g::Vector{Vector{Int}}
    site_x::Vector{Float64}
    site_y::Vector{Float64}
    site_geoid::Vector{String}  # "" if the site is in no block group
    site_id::Vector{Int}        # j in pantries.csv / grid_<delta>.csv
    # pairs within reach
    p_i::Vector{Int}
    p_j::Vector{Int}
    p_d::Vector{Float64}
    pairs_of_i::Vector{Vector{Int}}
    pairs_of_j::Vector{Vector{Int}}
    E_g::Dict{String,Int}                  # existing pantries per block group
    C_g::Dict{String,Vector{Int}}          # candidate indices (1:nC) per block group
end

function load_instance(delta::Integer; dmax = 3000.0, demand = "h_pov185", data_dir = DATA_DIR)
    moe = replace(demand, "h_" => "moe_")
    S = Dict(:i => String, :GEOID => String)
    blocks   = CSV.read(joinpath(data_dir, "demand_blocks.csv"), DataFrame; types = S, validate = false)
    bgs      = CSV.read(joinpath(data_dir, "blockgroup_demand.csv"), DataFrame; types = S, validate = false)
    pantries = CSV.read(joinpath(data_dir, "pantries.csv"), DataFrame; types = S, validate = false)
    grid     = CSV.read(joinpath(data_dir, "grid_$(delta).csv"), DataFrame; types = S, validate = false)

    bgs = bgs[bgs.included, :]
    bg_index = Dict(g => k for (k, g) in enumerate(bgs.GEOID))
    # A block is a demand point if its group has an estimate or a margin (the adversary can
    # create demand in a group whose estimate is 0).
    keep = [haskey(bg_index, g) && (bgs[bg_index[g], demand] > 0 || bgs[bg_index[g], moe] > 0)
            for g in blocks.GEOID]
    blocks = blocks[keep, :]
    nI = nrow(blocks)
    g_of_i = [bg_index[g] for g in blocks.GEOID]
    bg_moe = Float64.(bgs[!, moe])
    dev = Float64.(blocks.share) .* bg_moe[g_of_i]
    blocks_of_g = [Int[] for _ in 1:nrow(bgs)]
    for i in 1:nI
        push!(blocks_of_g[g_of_i[i]], i)
    end

    nE, nC = nrow(pantries), nrow(grid)
    site_x = Float64.(vcat(pantries.X, grid.X))
    site_y = Float64.(vcat(pantries.Y, grid.Y))
    site_geoid = String[coalesce(g, "") for g in vcat(pantries.GEOID, grid.GEOID)]
    site_id = Int.(vcat(pantries.j, grid.j))

    p_i, p_j, p_d = Int[], Int[], Float64[]
    bx, by = Float64.(blocks.x_i), Float64.(blocks.y_i)
    for i in 1:nI, j in 1:(nE + nC)
        d = hypot(bx[i] - site_x[j], by[i] - site_y[j])
        if d <= dmax
            push!(p_i, i); push!(p_j, j); push!(p_d, d)
        end
    end
    pairs_of_i = [Int[] for _ in 1:nI]
    pairs_of_j = [Int[] for _ in 1:(nE + nC)]
    for p in eachindex(p_i)
        push!(pairs_of_i[p_i[p]], p)
        push!(pairs_of_j[p_j[p]], p)
    end

    E_g = Dict{String,Int}()
    for g in site_geoid[1:nE]
        g == "" || (E_g[g] = get(E_g, g, 0) + 1)
    end
    C_g = Dict{String,Vector{Int}}()
    for c in 1:nC
        g = site_geoid[nE + c]
        g == "" || push!(get!(C_g, g, Int[]), c)
    end

    return Instance(delta, dmax, demand, nI, nE, nC, String.(blocks.i), bx, by,
                    Float64.(blocks[!, demand]), dev, g_of_i, String.(bgs.GEOID),
                    Float64.(bgs[!, demand]), bg_moe, blocks_of_g, site_x, site_y,
                    site_geoid, site_id, p_i, p_j, p_d, pairs_of_i, pairs_of_j, E_g, C_g)
end

capacity(inst, p, j) = j <= inst.nE ? p.c_exist : p.c_new

function new_model(p::Params; mip::Bool)
    m = direct_model(Gurobi.Optimizer(grb_env()))
    set_attribute(m, "OutputFlag", p.verbose ? 1 : 0)
    p.threads > 0 && set_attribute(m, "Threads", p.threads)
    if mip
        set_attribute(m, "MIPGap", p.mip_gap)
        set_attribute(m, "TimeLimit", p.time_limit)
    end
    return m
end

# --------------------------------------------------------------------------- #
# Master problem
# --------------------------------------------------------------------------- #
mutable struct Master
    model::Model
    b::Vector{VariableRef}
    t::VariableRef
    scenarios::Vector{Vector{Float64}}
    w::Vector{Vector{VariableRef}}      # assignment variables per scenario
    u::Vector{Vector{VariableRef}}
end

function check_caps(inst, p)
    floor_ = maximum(values(inst.E_g); init = 0)
    p.J_MAX === nothing || p.J_MAX >= floor_ ||
        error("J_MAX = $(p.J_MAX) is below the largest existing count ($floor_): infeasible.")
end

function new_master(inst::Instance, p::Params)
    check_caps(inst, p)
    m = new_model(p; mip = true)
    @variable(m, b[1:inst.nC], Bin)
    @variable(m, t)
    @objective(m, Min, t)
    @constraint(m, sum(b) <= p.K)                                           # (5)
    for (g, cs) in inst.C_g
        if p.J_MAX !== nothing && get(inst.E_g, g, 0) + length(cs) > p.J_MAX
            @constraint(m, get(inst.E_g, g, 0) + sum(b[c] for c in cs) <= p.J_MAX)   # (6)
        end
        if p.N_NEW !== nothing && length(cs) > p.N_NEW
            @constraint(m, sum(b[c] for c in cs) <= p.N_NEW)                # (6') new only
        end
    end
    return Master(m, b, t, Vector{Float64}[], Vector{VariableRef}[], Vector{VariableRef}[])
end

"Add constraints (1)-(4), (7) and (8) for demand scenario h."
function add_scenario!(M::Master, inst::Instance, p::Params, h::Vector{Float64})
    m, b = M.model, M.b
    np = length(inst.p_i)
    w = @variable(m, [1:np], lower_bound = 0)
    u = @variable(m, [1:inst.nI], lower_bound = 0)
    for i in 1:inst.nI                                                      # (1)
        @constraint(m, sum(w[q] for q in inst.pairs_of_i[i]; init = AffExpr(0.0)) + u[i] == h[i])
    end
    for j in 1:(inst.nE + inst.nC)                                          # (2), (3)
        ps = inst.pairs_of_j[j]
        isempty(ps) && continue
        if j <= inst.nE
            @constraint(m, sum(w[q] for q in ps) <= p.c_exist)
        else
            @constraint(m, sum(w[q] for q in ps) <= p.c_new * b[j - inst.nE])
        end
    end
    if p.tighten                                                            # (4)
        for q in 1:np
            j = inst.p_j[q]
            j > inst.nE && @constraint(m, w[q] <= h[inst.p_i[q]] * b[j - inst.nE])
        end
    end
    @constraint(m, M.t >= sum(inst.p_d[q] * w[q] for q in 1:np) + p.q * sum(u))   # (8)
    push!(M.scenarios, copy(h)); push!(M.w, w); push!(M.u, u)
    return M
end

# --------------------------------------------------------------------------- #
# Assignment LP for fixed build decisions (used by the adversary and for reporting)
# --------------------------------------------------------------------------- #
struct AssignLP
    model::Model
    w::Vector{VariableRef}
    u::Vector{VariableRef}
    dem::Vector{ConstraintRef}
    cap_new::Dict{Int,ConstraintRef}     # candidate index c -> capacity constraint
end

function build_assign_lp(inst::Instance, p::Params)
    m = new_model(p; mip = false)
    set_attribute(m, "Method", 1)        # dual simplex: fast re-solves after rhs changes
    np = length(inst.p_i)
    @variable(m, w[1:np] >= 0)
    @variable(m, u[1:inst.nI] >= 0)
    dem = [@constraint(m, sum(w[q] for q in inst.pairs_of_i[i]; init = AffExpr(0.0)) + u[i] == inst.hhat[i])
           for i in 1:inst.nI]
    cap_new = Dict{Int,ConstraintRef}()
    for j in 1:(inst.nE + inst.nC)
        ps = inst.pairs_of_j[j]
        isempty(ps) && continue
        if j <= inst.nE
            @constraint(m, sum(w[q] for q in ps) <= p.c_exist)
        else
            cap_new[j - inst.nE] = @constraint(m, sum(w[q] for q in ps) <= 0.0)
        end
    end
    @objective(m, Min, sum(inst.p_d[q] * w[q] for q in 1:np) + p.q * sum(u))
    return AssignLP(m, w, u, dem, cap_new)
end

"Solve the assignment for build vector bval and demand h. Returns cost and duals of (1)."
function assign!(A::AssignLP, inst, p, bval, h)
    for (c, con) in A.cap_new
        set_normalized_rhs(con, p.c_new * bval[c])
    end
    for i in 1:inst.nI
        set_normalized_rhs(A.dem[i], h[i])
    end
    optimize!(A.model)
    termination_status(A.model) == OPTIMAL || error("assignment LP: $(termination_status(A.model))")
    # JuMP shadow_price is the objective IMPROVEMENT per unit of rhs, so negate it: the
    # cost of one more person at block i, between 0 and q.
    duals = -shadow_price.(A.dem)
    return objective_value(A.model), duals
end

function assignment_stats(A::AssignLP, inst, h)
    wv, uv = value.(A.w), value.(A.u)
    served = sum(wv)
    return (demand = sum(h), served = served, unserved = sum(uv),
            avg_dist_m = served > 0 ? sum(inst.p_d .* wv) / served : NaN)
end

# --------------------------------------------------------------------------- #
# Adversary: dual-based local search over U_gamma (README2, "Adversary step in detail")
# --------------------------------------------------------------------------- #
function demand_from_z(inst, z)
    return inst.hhat .+ inst.dev .* z[inst.g_of_i]
end

function best_z(inst, gamma, score)
    z = zeros(length(score))
    gamma <= 0 && return z
    order = sortperm(score; rev = true)
    left = gamma
    for g in order
        (left <= 0 || score[g] <= 0) && break
        z[g] = min(1.0, left)
        left -= z[g]
    end
    return z
end

function adversary(A::AssignLP, inst, p, bval; max_iter = 20)
    z = zeros(length(inst.bg_moe))
    h = inst.hhat
    cost, duals = assign!(A, inst, p, bval, h)
    for _ in 1:max_iter
        score = [inst.bg_moe[g] == 0 ? 0.0 :
                 sum(inst.dev[i] * duals[i] for i in inst.blocks_of_g[g]; init = 0.0)
                 for g in eachindex(inst.bg_moe)]
        znew = best_z(inst, p.gamma, score)
        znew == z && break
        hnew = demand_from_z(inst, znew)
        cnew, dnew = assign!(A, inst, p, bval, hnew)
        cnew <= cost * (1 + 1e-9) && break
        z, h, cost, duals = znew, hnew, cnew, dnew
    end
    return (cost = cost, h = h, z = z)
end

# --------------------------------------------------------------------------- #
# Cutting-plane loop
# --------------------------------------------------------------------------- #
function solve_robust(inst::Instance, p::Params; log = true)
    inst.delta == p.delta && inst.dmax == p.dmax && inst.demand == p.demand ||
        error("Instance and Params disagree on delta / dmax / demand.")
    t0 = time()
    M = new_master(inst, p)
    add_scenario!(M, inst, p, copy(inst.hhat))
    A = build_assign_lp(inst, p)
    rounds = NamedTuple[]
    bval = zeros(inst.nC); bnom = zeros(inst.nC); adv = nothing
    tstar, lb, status = NaN, NaN, :none
    converged = false
    for r in 1:p.max_rounds
        ts = time()
        optimize!(M.model)
        st = termination_status(M.model)
        primal_status(M.model) == FEASIBLE_POINT || error("master round $r: $st, no solution")
        tstar, lb, status = objective_value(M.model), objective_bound(M.model), st
        bval = round.(value.(M.b))
        r == 1 && (bnom = copy(bval))              # round 1 = nominal model
        tm = time() - ts
        adv = adversary(A, inst, p, bval)
        push!(rounds, (round = r, scenarios = length(M.scenarios), master_obj = tstar,
                       master_bound = lb, adversary_cost = adv.cost, master_status = string(st),
                       master_sec = tm, round_sec = time() - ts))
        log && @printf("  round %d: scenarios %d  master %.6e (bound %.6e, %s, %.0fs)  adversary %.6e\n",
                       r, length(M.scenarios), tstar, lb, st, tm, adv.cost)
        if adv.cost <= tstar * (1 + p.tol)
            converged = true
            break
        end
        # Complete warm start (b*, every scenario's assignment, t). With b alone Gurobi must
        # build the assignment itself, which at 250 m / K = 20 found nothing in an hour.
        wstart = [value.(w) for w in M.w]; ustart = [value.(u) for u in M.u]
        assign!(A, inst, p, bval, adv.h)
        push!(wstart, value.(A.w)); push!(ustart, value.(A.u))
        add_scenario!(M, inst, p, adv.h)
        set_start_value.(M.b, bval)
        for k in eachindex(M.w)
            set_start_value.(M.w[k], wstart[k]); set_start_value.(M.u[k], ustart[k])
        end
        set_start_value(M.t, max(tstar, adv.cost))
    end

    worst = max(tstar, adv.cost)                 # lower bound on b*'s true worst case
    # Report the chosen sites under the estimate and under the worst scenario found
    assign!(A, inst, p, bval, inst.hhat);  nom = assignment_stats(A, inst, inst.hhat)
    nom_cost = objective_value(A.model)
    assign!(A, inst, p, bval, adv.h);      wc = assignment_stats(A, inst, adv.h)
    # Nominal sites under the same worst scenario: what robustness protects against
    nomsites_worst_cost, _ = assign!(A, inst, p, bnom, adv.h)
    built = findall(>(0.5), bval)
    sites = DataFrame(c = built, j = inst.site_id[inst.nE .+ built],
                      X = inst.site_x[inst.nE .+ built], Y = inst.site_y[inst.nE .+ built],
                      GEOID = inst.site_geoid[inst.nE .+ built])
    new_per_bg = isempty(built) ? 0 : maximum(values(countmap(sites.GEOID)))
    total_per_bg = maximum(values(merge(+, copy(inst.E_g), countmap(sites.GEOID))); init = 0)
    summary = (
        converged = converged, rounds = length(rounds), scenarios = length(M.scenarios),
        master_status = string(status), worst_cost = worst, robust_bound = lb,
        gap = (worst - lb) / worst, nominal_cost = nom_cost,
        nominal_sites_worst_cost = nomsites_worst_cost,
        sites_changed_vs_nominal = count(>(0.5), bval .- bnom),
        n_built = length(built), max_new_per_bg = new_per_bg, max_total_per_bg = total_per_bg,
        demand_nominal = nom.demand, served_nominal = nom.served, avg_dist_nominal_m = nom.avg_dist_m,
        demand_worst = wc.demand, served_worst = wc.served, avg_dist_worst_m = wc.avg_dist_m,
        groups_at_margin = count(>(1e-9), adv.z), solve_sec = time() - t0,
    )
    return (summary = summary, sites = sites, rounds = DataFrame(rounds), z = adv.z)
end

countmap(v) = (d = Dict{eltype(v),Int}(); for x in v; d[x] = get(d, x, 0) + 1; end; d)
