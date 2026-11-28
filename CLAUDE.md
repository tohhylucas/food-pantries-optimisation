# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MIT 15.C57 (Optimization Methods) course project: a capacitated facility location MILP choosing where to build up to `K` new food pantries in Suffolk County, MA (Boston, Chelsea, Revere, Winthrop), given 107 existing Greater Boston Food Bank (GBFB) pantries. The full formulation, assumptions (Appendix A) and open decisions (Appendix B) are in `README.md` (the interim report). `README2.md` is a newer draft of the same report that adds a robust-optimization extension (demand varies within ACS margins of error; scenario-based cutting planes with an uncertainty budget Γ).

Two stages, two languages:

1. **Python data pipeline** (`src/`) builds everything in `data/processed/` from `data/raw/`.
2. **Julia optimization model** (Julia 1.11, JuMP + Gurobi) reads `data/processed/`:
   - `notebooks/pantry_model.ipynb`: the nominal model, one parameter setting per *Run All*.
   - `src/robust_model.jl`: the robust model (README2 §3.2). `load_instance(delta)` + `solve_robust(inst, Params(...))`. `Params(gamma = 0)` reproduces the notebook's nominal objective exactly.
   - `src/run_sweeps.jl`: robust sensitivity sweeps (Γ = 26), resumable, writing to `results/sensitivity/`.

No tests, linter or build system exist.

## Commands

Run Python from the project root inside `.venv`. Docstrings use the Windows path `.venv/Scripts/python.exe`; on macOS use `.venv/bin/python`. Scripts are run with `-I` (isolated mode).

```bash
python -I src/prepare_pantries.py          # raw GBFB locator TSV -> data/raw/pantries/pantries_input.csv
python -I src/build_data.py [--dmax 3000]  # all processed data, distances, and data/processed/README.md + checks.md
python -I src/plot_map.py                  # static PNG maps for 1000/500/250/100 m grids
python -I src/plot_map.py --delta 750      # map at any grid spacing
python -I src/plot_map.py --interactive    # slider window
```

```bash
julia --project=@v1.11 -t auto src/run_sweeps.jl                    # all sweeps (caps, k_grid, capacity)
julia --project=@v1.11 -t auto src/run_sweeps.jl caps --delta=1000  # one sweep, one grid
julia --project=@v1.11 src/run_sweeps.jl --dry                      # list runs still to solve
```

Parallel workers: `--delta=250 --shard=1/2 --threads=6` (and `2/2`). Each worker writes its own `results/sensitivity/{runs,sites,rounds}_<tag>.csv`; the script skips runs found in any `runs*.csv`, and `notebooks/sensitivity.ipynb` stacks them for the plots. Delete those CSVs to rerun from scratch after changing the model.

Notebook: run from the `notebooks/` folder (paths are `../data/processed`) with *Run All*. Requires a Gurobi license. Outputs go to `notebooks/results/` (git-ignored). Tunable parameters (`DELTA`, `K`, `J_MAX`, `D_MAX`, `Q`, `C_EXIST`, `C_NEW`, `DEMAND`) are all in the second code cell.

## Architecture and non-obvious details

- **Demand is at census-block level, not block-group level.** `build_data.py` splits each block group's ACS counts over its 2020 census blocks by `POP20` share (`demand_blocks.csv`, ~5,500 points). The interim report text still describes block-group centres; the notebook uses blocks.
- **Demand columns:** `h_total`, `h_pov100` (below poverty), `h_pov185` (below 1.85× poverty), plus margins of error `moe_pov100` and `moe_pov185` (block-group level only, in `blockgroup_demand.csv` and `blockgroups.geojson`). The notebook and sweeps use `h_pov185`.
- **Robust uncertainty is per block group, not per block (decided).** The ACS margin $m_g$ exists only for the 664 block groups, so the adversary picks $z_g \in [0,1]$ per block group with $\sum_g z_g \le Γ$, and block $i$ in group $g$ gets $h_i = \hat h_i + \text{share}_i \, m_g z_g$ (`share` from `demand_blocks.csv`). Assignment stays at block level. Γ therefore counts block groups, so the √664 ≈ 26 anchor holds.
- **Two per-block-group caps:** `J_MAX` caps existing + new pantries (constraint 6); `N_NEW` caps new pantries only (6'). `nothing` = no cap. If `N_NEW ≥ J_MAX`, `N_NEW` never binds; `run_sweeps.jl` maps those cells to `N_NEW = J_MAX` and solves them once. The team dropped the `J_MAX` sweep: the `n_new` sweep varies `N_NEW` 1–5 with no `J_MAX` cap; the other sweeps keep the baseline `J_MAX = 2`, `N_NEW = 2`.
- **Site indexing convention:** existing pantries come first (`J_E = 1:nE`), then grid candidates (`J_C`). The same ordering is used when `build_data.py` concatenates sites for distances (grid IDs are offset by `m` = number of pantries).
- **The notebook recomputes distances itself** as a dense `d[i, j]` matrix from coordinates. The `distances_*.parquet` files from `build_data.py` are not read by the notebook. Changing `D_MAX` in the notebook does not require rerunning the pipeline.
- **`J_MAX` constraint** (max pantries per block group) groups sites by the block group they physically sit in (`GEOID` column on pantries and grid). It must be ≥ the largest existing pantry count in any block group (currently 2), or the model is infeasible; the notebook checks this.
- **Grids** (`DELTAS = [1000, 500, 250, 100]` in `build_data.py`) are laid over land with water removed; `special_area` flags sites like Logan Airport / large parks (tracts 98xx).
- **All geometry is in EPSG:26986 (metres).** Lon/lat (EPSG:4326) is used only for export.
- **`data/processed/README.md` and `checks.md` are generated** by `write_readme()` / `write_checks_log()` in `build_data.py`. Edit the generator, not the files, or changes will be overwritten on the next run.
- `plot_map.py` imports `make_grid`, `OUT`, `CRS_M` from `build_data.py`.
- The statewide census-block zip (102 MB) is git-ignored; `build_data.py` uses the committed Suffolk extract `data/raw/tiger_block/suffolk_blocks_2020.csv` and only needs the zip if that extract is missing. Pantry geocoding calls the Census Geocoder API (network access) when run.
- **Capacity:** the team uses 900 people/month for every pantry, existing and new (Massachusetts network average, MEFAP FY23; not formalised). The notebook on `main` still has the old placeholders `C_EXIST = 800`, `C_NEW = 1500`. Every pantry is full in all runs so far, so results are capacity-driven and people served = total capacity in reach.

## Writing style

The READMEs and generated docs use plain English, short sentences, and explain every symbol and table column. Keep that style when editing them.
