# Siting New Food Pantries in Suffolk County, MA: Interim Report

*15.C57 Optimization Methods · Interim report · November 2026*

## 1. Problem description

Food pantries in Suffolk County (Boston, Chelsea, Revere and Winthrop) are unevenly spread relative to where low-income residents live, so some people must travel far or are not served at all.

We ask: given the 107 existing pantries, where should up to $K$ new pantries be built so that

- as many people in need as possible are served,
- travel distances stay short,
- no pantry serves more people than its capacity, and
- the recommended sites still work if the survey-based demand counts are somewhat off?

## 2. Data

**Demand.** American Community Survey 2020–2024 5-year estimates, Table C17002 (ratio of income to poverty level), for the county's 681 block groups. 17 block groups have nobody whose poverty status is determined and are excluded, leaving 664. The estimated number of people to serve in block group $i$, written $\hat h_i$, is one of three counts:

| Measure | Who it counts | County total |
|---|---|---|
| Below poverty | income below the poverty line | 119,889 |
| Below 1.85 × poverty | income below 1.85 times the poverty line | 210,891 |
| Everyone | all people with poverty status determined | 740,754 |

**Margins of error.** Every ACS estimate comes with a 90% margin of error. For a count that sums several table cells, we use the Census Bureau's approximation: the margin of error is the square root of the sum of the squared cell margins. For the 1.85 × poverty measure this sums cells 002 to 006 of C17002:

$$
\hat h_i = \sum_{k=2}^{6} E_{00k,i}, \qquad m_i = \sqrt{\sum_{k=2}^{6} M_{00k,i}^2}
$$

For the below-poverty measure the sums run over cells 002 and 003 only. $\hat h_i$ and $m_i$ always use the same cells. The margins are large: for the below-poverty count, the median block group's margin is 87% of its estimate.

**Geography.** 2024 TIGER/Line polygons give each block group's boundary. Its demand point $(x_i, y_i)$ is the 2020 Census population-weighted centre of population. Removing water (Boston Harbor, rivers, ponds) leaves 150.8 km² of land. All coordinates are in metres (EPSG:26986).

**Supply.** We use the 107 existing pantries listed by the Greater Boston Food Bank (GBFB) partner locator. All 107 were geocoded with the Census Geocoder and all fall inside the county. Their capacities $c_j$ are not published and have been requested from GBFB.

**Candidate sites.** These are the points of a regular grid with spacing $\Delta$ laid over the land, so a new pantry can be placed anywhere at that resolution. There are 154, 617, 2,429 and 15,104 sites at $\Delta$ = 1000, 500, 250 and 100 m. The grids are nested: every 1000 m site is also a 500 m site, and every 500 m site is also a 250 m site and a 100 m site (the 250 m and 100 m grids are not nested in each other).

## 3. Methods

We use a capacitated facility location model, a mixed-integer optimization problem, and make it robust to demand uncertainty with a scenario-based cutting-plane method.

**Notation.**

| Symbol | Meaning |
|---|---|
| $I$ | block groups with people to serve |
| $J_E$, $J_C$ | existing pantries; candidate grid sites |
| $d_{ij}$ | straight-line distance from block group $i$ to site $j$, in metres |
| $A_i$ | sites within reach of block group $i$: $A_i = \lbrace j : d_{ij} \le D_{\max} \rbrace$ |
| $\hat h_i$, $m_i$ | estimated people to serve in block group $i$ and its margin of error |
| $h^k_i$ | people to serve in block group $i$ under demand scenario $k$ |
| $\mathcal S$ | the set of demand scenarios $k$ in the model; scenario 0 is $h^0 = \hat h$ |
| $c_j$ | capacity of pantry $j$, in people |
| $K$ | maximum number of new pantries |
| $J_{\max}$ | maximum total pantries per block group |
| $E_g$, $C_g$ | number of existing pantries and set of candidate sites physically in block group $g$ |
| $q$ | penalty per person left unserved, in metres |
| $\Gamma$ | uncertainty budget (see below) |

**Decision variables.** $b_j \in \lbrace 0,1 \rbrace$ equals 1 if a pantry is built at candidate site $j$. For each scenario $k$: $w^k_{ij} \ge 0$ is the number of people from block group $i$ served at pantry $j$, and $u^k_i \ge 0$ is the number of people in block group $i$ left unserved. $t$ is the worst-case cost across scenarios. The build decisions $b_j$ are shared by all scenarios, while the assignments $w^k, u^k$ can differ by scenario.

### 3.1 Nominal model

With one scenario ($\mathcal S = \lbrace 0 \rbrace$, $h^0 = \hat h$) the model is as follows. We drop the superscript here for readability.

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

### 3.2 Robust model: uncertain demand

The ACS counts $\hat h_i$ are estimates, so the true demand in block group $i$ may differ. We protect against this with a budgeted uncertainty set, in the style of the course lectures (L13–L14):

$$
\mathcal U_\Gamma = \lbrace h : h_i = \hat h_i + m_i z_i, \ \ 0 \le z_i \le 1, \ \ \textstyle\sum_{i \in I} z_i \le \Gamma \rbrace
$$

Each block group can deviate upward by at most its own margin of error $m_i$ (the box part), and the total deviation, measured in margins, is at most $\Gamma$ (the budget part). Setting $\Gamma = 0$ gives the nominal model. Setting $\Gamma = |I| = 664$ gives the full worst case, where every block group is at the top of its margin. We want values in between, because it is unrealistic for every estimate to be wrong in the same direction at once. Only upward deviations are modelled, since extra demand never lowers the cost.

**Robust problem.** We want the build decisions $b$ that minimise the worst-case cost over all $h \in \mathcal U_\Gamma$, where for each $h$ the people are assigned as well as possible:

$$
\min_{b \text{ satisfying (5),(6)}} \ \max_{h \in \mathcal U_\Gamma} \ \Big[ \min_{w, u \text{ satisfying (1)--(4),(7)}} \ \sum_{i}\sum_{j \in A_i} d_{ij} w_{ij} + q \sum_i u_i \Big]
$$

The build decisions are made first. The assignment of people then adapts to the realised demand.

**Why this needs more than adding the set to the model.** If the deviations $z$ were variables in the model, the optimiser would set them to 0, because more demand never helps. The deviations must be chosen by an adversary. Also, which block groups are worst depends on where we build, because extra demand only matters where nearby pantries are full. Finally, (1) is an equality, so the assignment $(w, u)$ must be allowed to differ across demand scenarios.

**Scenario formulation (master problem).** We keep a finite list $\mathcal S$ of demand scenarios, each a fixed vector $h^k \in \mathcal U_\Gamma$, and give each scenario its own assignment variables. Constraints (1)–(4) and (7) are repeated for every $k \in \mathcal S$, with $w^k, u^k, h^k$ in place of $w, u, h$. Constraints (5) and (6) appear once. A new constraint (8) links the scenarios.

$$
\min \ t
$$

**(8) The worst-case cost is at least the cost in every scenario.**

$$
t \ge \sum_{i \in I} \sum_{j \in A_i} d_{ij} w^k_{ij} + q \sum_{i \in I} u^k_i \quad \forall k \in \mathcal S
$$

Because each $h^k$ is data, the master problem is an ordinary mixed-integer linear program of the same type as the nominal model, with a larger number of continuous variables.

**Cutting-plane algorithm** (L14):

1. Start with $\mathcal S = \lbrace 0 \rbrace$ and $h^0 = \hat h$.
2. Solve the master problem. Call the optimal build decisions $b^\ast$ and optimal value $t^\ast$.
3. *Adversary step.* With $b^\ast$ fixed, find the demand in $\mathcal U_\Gamma$ for which the best assignment is most expensive. Call it $h^{\text{new}}$, and let $V$ be the cost of the best assignment under $h^{\text{new}}$ (a linear program).
4. If $V \le t^\ast + \varepsilon$, stop: $b^\ast$ is robust. Otherwise add $h^{\text{new}}$ to $\mathcal S$ and return to step 2.

**Adversary step in detail.** For fixed $b$, the cost of the best assignment is a convex function of $h$, so its maximum over $\mathcal U_\Gamma$ is reached at a corner of the set, where roughly $\Gamma$ block groups sit at the top of their margin and the rest sit at their estimate. We find it by local search:

1. Solve the assignment LP at the current demand $h$ and read the dual value $\pi_i$ of each block group's demand constraint (1). This is the cost of one extra person in block group $i$.
2. Choose $z$ to maximise $\sum_i \pi_i m_i z_i$ over the set: give $z_i = 1$ to the $\lfloor\Gamma\rfloor$ block groups with the largest $\pi_i m_i$, and the fractional remainder to the next one.
3. Set $h_i = \hat h_i + m_i z_i$ and re-solve the LP. Repeat until the cost stops increasing.

This local search can miss the true worst case, so the value it finds is a lower bound on the worst case for $b^\ast$. Because the dual values $\pi_i$ lie between 0 and $q$, the exact adversary can be written as a mixed-integer linear program if needed.

**Implementation.** The distances $d_{ij}$ and reachable sets $A_i$ are computed before solving. We implement the model in Julia with JuMP. Scenario 0 with $\Gamma = 0$ reproduces the nominal model, which gives a direct check of the code.

**Planned analysis.** We will vary $K$, $c_j$, $D_{\max}$, $\Delta$, $q$ and $\Gamma$. For $\Gamma$ we solve a grid of values and plot the price of robustness (objective and people served against $\Gamma$), and we count how many of the chosen sites change as $\Gamma$ grows. As an anchor, the central limit theorem argument from L13 suggests $\Gamma$ of order $\sqrt{|I|} \approx 26$. Finally, we fix the chosen sites and draw demand from $h_i \sim \mathcal N(\hat h_i, (m_i/1.645)^2)$, truncated at 0, re-solving the assignment for each draw. This checks that the robust sites do better than the nominal sites under random errors, and not only under our adversary.

## 4. Expected results

**Preliminary run (nominal model).** The capacities in this run are placeholders, not real data.

| Setting | Value |
|---|---|
| People to serve | below poverty (119,889) |
| Capacity: existing / new pantry | 800 / 1,500 people |
| $K$, $\Delta$, $D_{\max}$, $q$ | 10 new pantries, 1000 m, 3 km, 5,000 m |
| **People served** | **100,600 (83.9%)** |
| **Average distance travelled** | **0.45 km** |
| Optimality gap | within 1% of the proven optimum |

Every pantry is full in this run, so the result is driven by capacity. Real capacity data is therefore our top priority. The same reason suggests the recommended sites may change little as $\Gamma$ grows: when capacity binds everywhere, extra demand mostly becomes unserved demand wherever the pantries are placed. Real capacities will decide whether robustness changes the recommendations.

**Final report.** We expect to deliver:

1. a map of the recommended new sites;
2. a curve of people served and average travel distance as $K$ increases, where we expect each additional pantry to add less coverage than the one before;
3. a list of block groups that remain underserved even at large $K$, because their nearby pantries are full or no candidate site is close enough;
4. a price-of-robustness curve against $\Gamma$ and a comparison of nominal and robust site sets.

We also expect the recommended sites to stabilise once the grid is fine relative to block-group size.

## 5. Practical implications

The model gives the food bank a transparent, data-based ranking of where new pantries add the most coverage. It also shows how much each additional pantry is worth, which helps with budget decisions. The robustness analysis shows which recommendations hold up despite uncertain survey data, and how much coverage we give up to be protected against it.

**Limitations.** Residents are placed at block-group centres. Distances are straight-line rather than travel times. Capacity data is still missing. Only GBFB-network pantries are included. The model does not force people to use their nearest pantry. The uncertainty set is a budget set, while ACS margins combine as a root sum of squares, which an ellipsoidal set would capture more closely (at the cost of a conic model). The adversary step is a local search, so the reported worst case is a lower bound on the true worst case. Block groups with an estimate of 0 still have a positive margin, so the adversary can create demand there.

<div style="page-break-after: always;"></div>

## Appendix A: Key assumptions

| # | Assumption | Why it is reasonable | What changes if it does not hold |
|---|---|---|---|
| A1 | **Each block group's demand sits at one point**, its 2020 population-weighted centre. | Poverty counts are not published below block-group level, and block groups are small (a few hundred metres across). | People at the edges of a block group are nearer to or farther from pantries than modelled. |
| A2 | **People in need live where all residents live, on average.** The centre of *all* 2020 residents is used for people below the poverty line in 2020–2024. | There is no official finer-grained data on where poor residents live. Massachusetts block-group boundaries did not change over this period. | Block groups with uneven poverty, or with large new housing since 2020, have slightly misplaced demand points. |
| A3 | **Census estimates are the centre of the uncertainty set.** True demand lies within $[\hat h_i, \hat h_i + m_i]$, with at most $\Gamma$ margins used in total. | They are the best available counts at this level, and the margins are published. | Margins are large (median 87% of the estimate). Margins of summed cells use the Census root-sum-of-squares rule, which assumes independent cells. The robustness analysis in Section 3.2 addresses this. |
| A4 | **Travel distance is straight-line distance**, capped at $D_{\max}$. | It is simple and consistent across the county. | Real walking or transit trips are longer, especially across water, highways and rail lines. $d_{ij}$ can be replaced by network distances without changing the rest of the model. |
| A5 | **Existing supply is the GBFB network**, and every GBFB site counts, including meal programmes and mobile markets. | It is the largest maintained list of food-assistance sites in the county. | Independent pantries are missing. For example, Winthrop Community Food Pantry is not in the network, so Winthrop has no existing pantry in our data. |
| A6 | **All pantries of a type have the same capacity**: one value for existing pantries, one for new ones. | Real capacities are not yet available. | Until GBFB data arrives, results show *where* need is unmet, not exact numbers served. |
| A7 | **Assignments adapt to realised demand.** Build decisions are made first, and people are then assigned for whatever demand occurs. | Pantries are built once, but who uses which pantry changes over time. | If people could not be reassigned, a fixed-share model would be needed, which is more conservative. |

<div style="page-break-after: always;"></div>

## Appendix B: Decisions to make going forward

| # | Decision | Options | Recommendation | Why it matters |
|---|---|---|---|---|
| D1 | **Who counts as "in need"**, $\hat h_i$ and $m_i$ | Below poverty (119,889); below 1.85 × poverty (210,891); everyone (740,754) | Below poverty, then confirm against the pantries' actual eligibility rules | It sets the size and location of demand. $m_i$ must be computed from the same table cells as $\hat h_i$ (cells 002–003 for below poverty, 002–006 for 1.85 ×). |
| D2 | **Capacity of existing pantries**, $c_j$ for $j \in J_E$ | GBFB data; a proxy such as weekly opening hours from the locator; a uniform value | Request from GBFB; use opening hours as a fallback | Every pantry is full in our preliminary run, so this drives the results. Capacity must be in *people per period*; GBFB likely reports pounds or households, so a conversion is needed. |
| D3 | **Capacity of a new pantry**, $c_j$ for $j \in J_C$ | A fixed value; the median existing capacity; a range | The median existing capacity, once known | It sets how much each new pantry can add. |
| D4 | **Participation rate** | Serve all of $\hat h_i$, or only the share of people who actually use pantries | To be decided | With realistic capacities, serving everyone in need may be impossible, and unserved demand then dominates the objective. |
| D5 | **Objective and penalty** $q$ | $q - d$ with a chosen $q$, or $q = D_{\max}$, or distance decay $1/(d + d_0)$ | $q = D_{\max}$: serving someone is worth $D_{\max} - d$, which falls to zero at the reach limit, with no extra parameter | We tested raw $1/d$ and rejected it. At $\Delta$ = 500 m it placed pantries within 6–34 m of block-group centres, served fewer people (99,686 vs 100,600) and had a longer average distance (555 m vs 431 m). |
| D6 | **Reach limit** $D_{\max}$ | 1 to 3 km | Report a sensitivity range rather than one value | It decides which pairs are allowed at all. At 3 km every block group can reach at least one site. |
| D7 | **Grid spacing** $\Delta$ | 1000, 500, 250 or 100 m | 1000 m to explore, 500 m for final results, 250 m to check stability, 100 m for the finest placement | Finer grids give more site choices but take longer to solve. Robust runs repeat the master problem, so start at 1000 m. |
| D8 | **Range of** $K$ | 0 to 20 or more | 0 to 20 for the curve of people served against $K$ | It shows diminishing returns and supports budget decisions. |
| D9 | **Distance type** | Straight-line; walking network; transit time | Straight-line now; network distance if time allows | Barriers such as the harbour and highways make straight-line distance optimistic. |
| D10 | **Completeness of supply** | GBFB only; add independents from Project Bread and Mass 211 | Add independents where they fill gaps (e.g. Winthrop) | Missing pantries make some areas look more underserved than they are. |
| D11 | **Unsuitable sites** | Allow all land; exclude Logan Airport and large parks (tracts 98xx) | Exclude them for final results | Otherwise the model can choose sites where a pantry cannot be built. |
| D12 | **Nearest-pantry rule** | Free assignment; force people to their nearest open pantry | Free assignment for now | Forcing it is more realistic but adds constraints and makes the model harder to solve. |
| D13 | **Robustness method** | Budget set solved by cutting planes; budget set solved by a dual reformulation; ellipsoidal set | Budget set $\mathcal U_\Gamma$ solved by cutting planes (L14), keeping constraints (1)–(7) unchanged | It keeps the nominal model intact and gives a price-of-robustness curve. The dual reformulation is exact but rewrites the constraints. |
| D14 | **Range of** $\Gamma$ | 0 to 664 | A grid from 0 to about 100, with the $\sqrt{\lvert I\rvert}\approx 26$ anchor highlighted | It sets how many block groups the adversary can push to their margin at once. |
| D15 | **Adversary step** | Local search with dual values; exact bilinear MILP | Local search first; exact MILP to verify the final answer | Local search is fast but may understate the worst case. |