# Siting New Food Pantries in Suffolk County, MA: Interim Report

*15.C57 Optimization Methods · Interim report · November 2026*

## 1. Problem description

Food pantries in Suffolk County (Boston, Chelsea, Revere and Winthrop) are unevenly spread relative to where low-income residents live, so some people must travel far or are not served at all.

We ask: given the 107 existing pantries, where should up to $K$ new pantries be built so that

- as many people in need as possible are served,
- travel distances stay short, and
- no pantry serves more people than its capacity?

## 2. Data

**Demand.** American Community Survey 2020–2024 5-year estimates, Table C17002 (ratio of income to poverty level), for the county's 681 block groups. 17 block groups have nobody whose poverty status is determined and are excluded, leaving 664. The number of people to serve in block group $i$, written $h_i$, is one of three counts:

| Measure | Who it counts | County total |
|---|---|---|
| Below poverty | income below the poverty line | 119,889 |
| Below 1.85 × poverty | income below 1.85 times the poverty line | 210,891 |
| Everyone | all people with poverty status determined | 740,754 |

The margins of error are large. For the below-poverty count, the median block group's margin is 87% of its estimate.

**Geography.** 2024 TIGER/Line polygons give each block group's boundary. Its demand point $(x_i, y_i)$ is the 2020 Census population-weighted centre of population. Removing water (Boston Harbor, rivers, ponds) leaves 150.8 km² of land. All coordinates are in metres (EPSG:26986).

**Supply.** We use the 107 existing pantries listed by the Greater Boston Food Bank (GBFB) partner locator. All 107 were geocoded with the Census Geocoder and all fall inside the county.

**Capacity.** No public source gives how many people an individual pantry serves: GBFB and the state report food volumes only per food bank, and the locator lists opening schedules but no volumes. We therefore give every pantry, existing or new, the same capacity, **$c_j$ = 900 people per month**. This is the Massachusetts network average: the four Massachusetts food banks' partners reported serving about 826,000 people every month through over 900 emergency food programs in 2023 ([MEFAP FY23 Core Food & MassGrown Summary Report](https://www.gbfb.org/wp-content/uploads/2024/05/GBFB_MEFAPFY23_Final-Report.pdf), p. 3), and 826,000 / 900 ≈ 900. Two other figures are consistent with it: GBFB distributed 107.3 million lb in FY23 (same report, Table 2) through more than 600 partner agencies, about 15,000 lb per agency per month; and a survey of 27 food pantries in Southern California found a median of 450 households per month ([community-engaged pantry study](https://pmc.ncbi.nlm.nih.gov/articles/PMC13059207/)), about 1,100 people at roughly 2.5 people per household. The 826,000 counts a person once at every program they use, and it includes meal programs and shelters, so 900 is an average rather than a measured value for any one pantry. We therefore test 600 and 1,200 people per month as well.

**Time unit.** Demand and capacity are both per month: each person in need is assumed to visit a pantry about once a month, which is how the capacity figure above is measured. Scaling both to a day would divide every term of the objective by the same factor and leave the solution unchanged.

**Candidate sites.** These are the points of a regular grid with spacing $\Delta$ laid over the land, so a new pantry can be placed anywhere at that resolution. There are 154, 617 and 2,429 sites at $\Delta$ = 1000, 500 and 250 m. The grids are nested: every 1000 m site is also a 500 m site, and every 500 m site is also a 250 m site.

## 3. Methods

We use a capacitated facility location model, a mixed-integer optimization problem.

**Notation.**

| Symbol | Meaning |
|---|---|
| $I$ | block groups with people to serve |
| $J_E$, $J_C$ | existing pantries; candidate grid sites |
| $d_{ij}$ | straight-line distance from block group $i$ to site $j$, in metres |
| $A_i$ | sites within reach of block group $i$: $A_i = \lbrace j : d_{ij} \le D_{\max} \rbrace$ |
| $h_i$ | people to serve in block group $i$ |
| $c_j$ | capacity of pantry $j$, in people per month (900 for every pantry; see Section 2) |
| $K$ | maximum number of new pantries |
| $J_{\max}$ | maximum total pantries per block group |
| $E_g$, $C_g$ | number of existing pantries and set of candidate sites physically in block group $g$ |
| $q$ | penalty per person left unserved, in metres |

**Decision variables.** $b_j \in \lbrace 0,1 \rbrace$ equals 1 if a pantry is built at candidate site $j$. $w_{ij} \ge 0$ is the number of people from block group $i$ served at pantry $j$. $u_i \ge 0$ is the number of people in block group $i$ left unserved.

**Objective.** Minimise total travel (person-metres) plus a penalty for every person left unserved:

$$
\min \ \sum_{i \in I} \sum_{j \in A_i} d_{ij} w_{ij} + q \sum_{i \in I} u_i
$$

**Constraints.** The model has seven groups of constraints.

**(1) Every person in need is either served or counted as unserved.**

$$
\sum_{j \in A_i} w_{ij} + u_i = h_i \quad \forall i \in I
$$

For each block group $i$, the people sent to pantries plus the people left unserved must add up to exactly the number in need, $h_i$. Nobody is counted twice or forgotten. The sum runs only over $A_i$, the sites within $D_{\max}$, so nobody can be sent to a pantry that is too far away. Anyone who cannot be placed goes into $u_i$, which the objective penalises at $q$ per person.

**(2) Existing pantries cannot serve more people than their capacity.**

$$
\sum_{i \in I : j \in A_i} w_{ij} \le c_j \quad \forall j \in J_E
$$

For each existing pantry $j$, the total number of people it serves, added up over every block group that can reach it, is at most its capacity $c_j$. Existing pantries are always open, so there is no build variable here.

**(3) A new pantry serves people only if it is built, and then only up to its capacity.**

$$
\sum_{i \in I : j \in A_i} w_{ij} \le c_j b_j \quad \forall j \in J_C
$$

This is constraint (2) for candidate sites, with the capacity multiplied by the build decision $b_j$. If site $j$ is not built, then $b_j = 0$ and the right-hand side is 0, so nobody can be served there. If it is built, then $b_j = 1$ and it can serve up to $c_j$ people. This is what links the assignment decisions $w_{ij}$ to the build decisions $b_j$.

**(4) Tightening constraint: a block group can use a new site only if it is built.**

$$
w_{ij} \le h_i b_j \quad \forall i \in I, \ j \in A_i \cap J_C
$$

Block group $i$ can send at most all $h_i$ of its people to site $j$, and none at all if $j$ is not built. Constraints (1) and (3) already imply this whenever $b_j$ is 0 or 1, so it removes no integer solution. It matters for the linear relaxation, where $b_j$ may take any value between 0 and 1. With (3) alone, a site can be "partly built" with $b_j$ equal to its load divided by $c_j$, which is very small when $c_j$ is large, and still serve that load. Constraint (4) forces $b_j \ge w_{ij} / h_i$ for every block group using the site. Fractional solutions must therefore open sites more fully, which gives a stronger lower bound and usually a faster branch-and-bound search.

**(5) At most $K$ new pantries are built.**

$$
\sum_{j \in J_C} b_j \le K
$$

This is the budget on new pantries. It is an inequality, so the model may build fewer than $K$ if additional pantries would not reduce the objective.

**(6) At most $J_{\max}$ total pantries per block group.**

$$
E_g + \sum_{j \in C_g} b_j \le J_{\max} \quad \forall g
$$

The cap counts existing and new pantries. Because existing pantries stay open, the smallest feasible cap is the largest existing count across all block groups. That count is 2 in the current data, so the notebook sets $J_{\max}=2$. The countywide limit $K$ also applies.

**(7) Variable domains.**

$$
w_{ij} \ge 0, \quad u_i \ge 0, \quad b_j \in \lbrace 0,1 \rbrace
$$

Numbers of people served and unserved cannot be negative, and each site is either built or not. We treat $w_{ij}$ and $u_i$ as continuous rather than whole numbers. This is a standard simplification: block groups contain hundreds of people, so rounding changes the results very little.

**How to read $q$.** Because every person is either served or unserved, the objective equals a constant minus $\sum_{i} \sum_{j} (q - d_{ij}) w_{ij}$. Minimising it is therefore the same as maximising $\sum_{i} \sum_{j} (q - d_{ij}) w_{ij}$: each person served at distance $d$ is worth $q - d$. A larger $q$ puts more weight on serving more people, and a smaller $q$ puts more weight on short trips.

**Implementation.** The distances $d_{ij}$ and reachable sets $A_i$ are computed before solving, so the model is a mixed-integer linear program. We will implement it in Julia with JuMP.

**Planned analysis.** We will vary $K$, $c_j$, $D_{\max}$, $\Delta$ and $q$. We will also test whether the chosen sites stay good when $h_i$ varies within its margin of error (robust optimization).

## 4. Expected results

**Preliminary run.** The capacities in this run (800 / 1,500) were placeholders chosen before the capacity estimate in Section 2. Later runs use 900 people per month for every pantry.

| Setting | Value |
|---|---|
| People to serve | below poverty (119,889) |
| Capacity: existing / new pantry | 800 / 1,500 people |
| $K$, $\Delta$, $D_{\max}$, $q$ | 10 new pantries, 1000 m, 3 km, 5,000 m |
| **People served** | **100,600 (83.9%)** |
| **Average distance travelled** | **0.45 km** |
| Optimality gap | within 1% of the proven optimum |

Every pantry is full in this run, so the result is driven by capacity. This is why we replaced the placeholders with the network-average estimate and test it from 600 to 1,200.

**Final report.** We expect to deliver:

1. a map of the recommended new sites;
2. a curve of people served and average travel distance as $K$ increases, where we expect each additional pantry to add less coverage than the one before;
3. a list of block groups that remain underserved even at large $K$, because their nearby pantries are full or no candidate site is close enough.

We also expect the recommended sites to stabilise once the grid is fine relative to block-group size.

## 5. Practical implications

The model gives the food bank a transparent, data-based ranking of where new pantries add the most coverage. It also shows how much each additional pantry is worth, which helps with budget decisions. The robustness test shows which recommendations hold up despite uncertain survey data.

**Limitations.** Residents are placed at block-group centres. Distances are straight-line rather than travel times. Pantry capacities are a network average (900 people per month), not measured per pantry. Only GBFB-network pantries are included. The model does not force people to use their nearest pantry.

<div style="page-break-after: always;"></div>

## Appendix A: Key assumptions

| # | Assumption | Why it is reasonable | What changes if it does not hold |
|---|---|---|---|
| A1 | **Each block group's demand sits at one point**, its 2020 population-weighted centre. | Poverty counts are not published below block-group level, and block groups are small (a few hundred metres across). | People at the edges of a block group are nearer to or farther from pantries than modelled. |
| A2 | **People in need live where all residents live, on average.** The centre of *all* 2020 residents is used for people below the poverty line in 2020–2024. | There is no official finer-grained data on where poor residents live. Massachusetts block-group boundaries did not change over this period. | Block groups with uneven poverty, or with large new housing since 2020, have slightly misplaced demand points. |
| A3 | **Census estimates are taken at face value.** | They are the best available counts at this level. | Margins are large (median 87% of the estimate). The robustness test addresses this. |
| A4 | **Travel distance is straight-line distance**, capped at $D_{\max}$. | It is simple and consistent across the county. | Real walking or transit trips are longer, especially across water, highways and rail lines. $d_{ij}$ can be replaced by network distances without changing the rest of the model. |
| A5 | **Existing supply is the GBFB network**, and every GBFB site counts, including meal programmes and mobile markets. | It is the largest maintained list of food-assistance sites in the county. | Independent pantries are missing. For example, Winthrop Community Food Pantry is not in the network, so Winthrop has no existing pantry in our data. |
| A6 | **Every pantry has the same capacity, 900 people per month**, existing and new alike. | Pantry-level volumes are not published; 900 is the Massachusetts network average (about 826,000 people per month through over 900 programs, MEFAP FY23). | Large pantries are under-stated and small ones over-stated, so individual sites may be full or idle in reality when the model says otherwise. Results are tested at 600 and 1,200. |
| A7 | **Each person in need visits a pantry about once a month**, so demand and capacity are both per month. | Pantry use is commonly reported as people served per month, which is how the capacity figure is measured. | If people visit more often, effective capacity per person is lower and more people go unserved. |

<div style="page-break-after: always;"></div>

## Appendix B: Decisions to make going forward

| # | Decision | Options | Recommendation | Why it matters |
|---|---|---|---|---|
| D1 | **Who counts as "in need"**, $h_i$ | Below poverty (119,889); below 1.85 × poverty (210,891); everyone (740,754) | Below poverty, then confirm against the pantries' actual eligibility rules | It sets the size and location of demand. Using 1.85 × also requires computing that count's margin of error for the robustness test. |
| D2 | **Capacity of existing pantries**, $c_j$ for $j \in J_E$ | GBFB data; a proxy such as weekly opening hours from the locator; a uniform value | **Decided:** a uniform 900 people per month (network average, Section 2), tested at 600 and 1,200. Replace with GBFB data if it becomes available | Every pantry is full in our preliminary run, so this drives the results. Capacity must be in *people per period*; GBFB likely reports pounds or households, so a conversion is needed. |
| D3 | **Capacity of a new pantry**, $c_j$ for $j \in J_C$ | A fixed value; the median existing capacity; a range | **Decided:** the same 900 people per month as an existing pantry | It sets how much each new pantry can add. |
| D4 | **Participation rate** | Serve all of $h_i$, or only the share of people who actually use pantries | To be decided | With realistic capacities, serving everyone in need may be impossible, and unserved demand then dominates the objective. |
| D5 | **Objective and penalty** $q$ | $q - d$ with a chosen $q$, or $q = D_{\max}$, or distance decay $1/(d + d_0)$ | $q = D_{\max}$: serving someone is worth $D_{\max} - d$, which falls to zero at the reach limit, with no extra parameter | We tested raw $1/d$ and rejected it. At $\Delta$ = 500 m it placed pantries within 6–34 m of block-group centres, served fewer people (99,686 vs 100,600) and had a longer average distance (555 m vs 431 m). |
| D6 | **Reach limit** $D_{\max}$ | 1 to 3 km | Report a sensitivity range rather than one value | It decides which pairs are allowed at all. At 3 km every block group can reach at least one site. |
| D7 | **Grid spacing** $\Delta$ | 1000, 500 or 250 m | 1000 m to explore, 500 m for final results, 250 m to check stability | Finer grids give more site choices but take longer to solve. |
| D8 | **Range of** $K$ | 0 to 20 or more | 0 to 20 for the curve of people served against $K$ | It shows diminishing returns and supports budget decisions. |
| D9 | **Distance type** | Straight-line; walking network; transit time | Straight-line now; network distance if time allows | Barriers such as the harbour and highways make straight-line distance optimistic. |
| D10 | **Completeness of supply** | GBFB only; add independents from Project Bread and Mass 211 | Add independents where they fill gaps (e.g. Winthrop) | Missing pantries make some areas look more underserved than they are. |
| D11 | **Unsuitable sites** | Allow all land; exclude Logan Airport and large parks (tracts 98xx) | Exclude them for final results | Otherwise the model can choose sites where a pantry cannot be built. |
| D12 | **Nearest-pantry rule** | Free assignment; force people to their nearest open pantry | Free assignment for now | Forcing it is more realistic but adds constraints and makes the model harder to solve. |
| D13 | **Robustness method** | Vary $h_i$ within its margin of error using a box or budget uncertainty set | A budgeted uncertainty set (course lectures L13–L14) | It shows which recommended sites survive survey uncertainty. |
