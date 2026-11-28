# Robust sensitivity sweeps (gamma = 26). Run from the project root:
#
#   julia --project=@v1.11 -t auto src/run_sweeps.jl                  # all sweeps
#   julia --project=@v1.11 -t auto src/run_sweeps.jl n_new k_grid     # some sweeps
#   julia --project=@v1.11 -t auto src/run_sweeps.jl --delta=1000,500 # some grids only
#   julia --project=@v1.11 -t auto src/run_sweeps.jl --dry            # list runs, solve nothing
#   julia --project=@v1.11 -t auto src/run_sweeps.jl --delta=250 --shard=1/2 --threads=6  # one parallel worker
#
# Each worker appends to its own results/sensitivity/{runs,sites,rounds}_<tag>.csv after every
# run (tag from --delta/--shard), so parallel workers never write the same file. Runs already
# in any runs*.csv are skipped, so an interrupted sweep resumes where it stopped.
#
# Sweeps (baseline: delta 500 m, K 10, J_MAX 2, N_NEW 2, capacity 900 for every pantry):
#   n_new     N_NEW in {1..5} x delta in {1000,500,250}, K = 10, no J_MAX cap.
#             (A J_MAX x N_NEW grid was solved earlier and then dropped; its J_MAX = 3, 4 runs
#             stay in the CSVs but are not plotted.)
#   k_grid    K in {0,2,...,20} x delta in {1000,500,250}
#   capacity  capacity in {600,900,1200} (existing and new alike) x K in {0,2,...,20}, delta 500

include(joinpath(@__DIR__, "robust_model.jl"))

const OUT_DIR = normpath(joinpath(@__DIR__, "..", "results", "sensitivity"))
const BASE = Params(delta = 500, K = 10, J_MAX = 2, N_NEW = 2, c_exist = 900.0, c_new = 900.0,
                    gamma = 26.0)
const DELTAS = [1000, 500, 250]
const KS = 0:2:20

with(p::Params; kw...) = Params(; (f => getfield(p, f) for f in fieldnames(Params))..., kw...)
capstr(x) = x === nothing ? "none" : string(x)
run_key(p::Params) = "d$(p.delta)_K$(p.K)_J$(capstr(p.J_MAX))_N$(capstr(p.N_NEW))_c$(Int(p.c_exist))-$(Int(p.c_new))_g$(p.gamma)"

"Effective new-pantry cap: N_NEW above J_MAX never binds, so map it to J_MAX."
canonical(p::Params) = (p.J_MAX !== nothing && p.N_NEW !== nothing && p.N_NEW > p.J_MAX) ?
                       with(p; N_NEW = p.J_MAX) : p

function sweep_runs(name)
    if name == "n_new"
        return [with(BASE; delta = d, J_MAX = nothing, N_NEW = N) for d in DELTAS for N in 1:5]
    elseif name == "k_grid"
        return [with(BASE; delta = d, K = k) for d in DELTAS for k in KS]
    elseif name == "capacity"
        return [with(BASE; c_exist = c, c_new = c, K = k) for c in (600.0, 900.0, 1200.0) for k in KS]
    end
    error("unknown sweep '$name' (n_new, k_grid, capacity)")
end

function append_csv(path, df)
    isempty(df) && return
    CSV.write(path, df; append = isfile(path), writeheader = !isfile(path))
end

function main(args)
    names = filter(a -> !startswith(a, "--"), args)
    isempty(names) && (names = ["n_new", "k_grid", "capacity"])
    dflag = filter(a -> startswith(a, "--delta="), args)
    deltas = isempty(dflag) ? DELTAS : parse.(Int, split(split(dflag[1], "=")[2], ","))
    dry = "--dry" in args
    flag(name) = (f = filter(a -> startswith(a, "--$name="), args); isempty(f) ? nothing : split(f[1], "=")[2])
    shard = flag("shard") === nothing ? (1, 1) : Tuple(parse.(Int, split(flag("shard"), "/")))
    threads = flag("threads") === nothing ? 0 : parse(Int, flag("threads"))
    tag = (isempty(dflag) ? "all" : "d" * join(deltas, "-")) * (shard == (1, 1) ? "" : "_s$(shard[1])of$(shard[2])")

    runs = unique(run_key, canonical.(vcat(sweep_runs.(names)...)))
    filter!(p -> p.delta in deltas, runs)
    sort!(runs; by = p -> (-p.delta, p.c_exist, p.K, capstr(p.J_MAX), capstr(p.N_NEW)))

    mkpath(OUT_DIR)
    runs_csv = joinpath(OUT_DIR, "runs_$tag.csv")
    done = Set{String}()
    for f in readdir(OUT_DIR; join = true)
        occursin(r"^runs.*\.csv$", basename(f)) && union!(done, CSV.read(f, DataFrame).run_key)
    end
    todo = filter(p -> !(run_key(p) in done), runs)
    todo = todo[shard[1]:shard[2]:end]
    println("$(length(runs)) runs in $(join(names, ", ")); $(length(runs) - length(todo)) already done; $(length(todo)) to solve")
    dry && (foreach(p -> println("  ", run_key(p)), todo); return)

    inst = nothing
    for (n, p) in enumerate(todo)
        if inst === nothing || inst.delta != p.delta
            inst = load_instance(p.delta; dmax = p.dmax, demand = p.demand)
        end
        key = run_key(p)
        println("[$n/$(length(todo))] $key")
        res = solve_robust(inst, with(p; threads = threads))
        s = res.summary
        @printf("  -> worst %.4e, served (worst) %.0f, %d sites changed vs nominal, %.0fs\n",
                s.worst_cost, s.served_worst, s.sites_changed_vs_nominal, s.solve_sec)
        row = DataFrame([merge((run_key = key, delta = p.delta, K = p.K, J_MAX = capstr(p.J_MAX),
                                N_NEW = capstr(p.N_NEW), c_exist = p.c_exist, c_new = p.c_new,
                                gamma = p.gamma, q = p.q, dmax = p.dmax, demand = p.demand,
                                mip_gap = p.mip_gap), s)])
        sites = insertcols!(copy(res.sites), 1, :run_key => key)
        rounds = insertcols!(copy(res.rounds), 1, :run_key => key)
        append_csv(joinpath(OUT_DIR, "sites_$tag.csv"), sites)
        append_csv(joinpath(OUT_DIR, "rounds_$tag.csv"), rounds)
        append_csv(runs_csv, row)          # last, so a crash mid-write reruns this run
    end
end

main(ARGS)
