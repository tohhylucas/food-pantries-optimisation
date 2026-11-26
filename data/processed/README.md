# How the model data was built

This folder holds the input data for the Suffolk County, MA food-pantry location model.
This page explains **what data we started with** and **what was done to it, step by step**.

The numbers on this page are filled in automatically by `src/build_data.py` each time it
runs (last run: 2026-11-25). A full technical log of every check is in
[`checks.md`](checks.md).

---

## The short version

1. **Count the people in need.** The Census reports, for each of the county's 681
   *block groups* (small neighbourhoods), how many people live below the poverty line.
2. **Put each block group on the map, then spread its people over its census blocks.** Each
   block group gets its boundary shape. Its people in need are then shared out over the
   census blocks inside it, in proportion to each block's 2020 population, so demand sits
   at 5,537 block points instead of 664 block-group centres.
3. **Draw the county's land.** Merge the shapes into one outline and remove harbour, river
   and pond water.
4. **Find the existing food pantries.** 107 sites were collected from the Greater Boston
   Food Bank's online locator, and their addresses were turned into map coordinates.
5. **Lay out possible new pantry sites.** A regular grid of points is placed over the land,
   one every 1000 m, 500 m or 250 m.
6. **Measure distances.** The distance is measured from every demand point (census block)
   to every pantry or grid point within 3 km.
7. **Draw maps** to check that everything looks right.

```
Census poverty table ─┐
Block-group shapes ───┼─► block groups with people counts + centres ─┐
Population centres ───┤                                               │
Census blocks ────────┴─► people in need per census block ────────────┤
Water areas ─────────────► county land outline ─► candidate grid ─────┼─► distances ─► maps
GBFB pantry locator ─────► cleaned pantry list ─► geocoded pantries ──┘
```

---

## What we started with

| # | Data | What it tells us | Source |
|---|---|---|---|
| 1 | **Census poverty table** (ACS 2020–2024, table C17002) | For each block group: number of people, split into 7 income bands relative to the poverty line, with a margin of error for each | data.census.gov (supplied by the team) |
| 2 | **Block-group boundaries** (TIGER/Line 2024) | The map shape of every block group | [census.gov](https://www2.census.gov/geo/tiger/TIGER2024/BG/tl_2024_25_bg.zip) |
| 3 | **Water areas** (TIGER/Line 2024) | Harbour, rivers and ponds inside the county | [census.gov](https://www2.census.gov/geo/tiger/TIGER2024/AREAWATER/tl_2024_25025_areawater.zip) |
| 4 | **County boundary** (TIGER/Line 2024) | The official county outline (used only as a cross-check) | [census.gov](https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip) |
| 5 | **Centres of population** (2020 Census) | Where people actually live within each block group | [census.gov](https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG25.txt) |
| 7 | **Census blocks** (TIGER/Line 2020, `tabblock20`) | For each census block: its 2020 population (`POP20`), housing units and an internal point | [census.gov](https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_25_tabblock20.zip) |
| 6 | **Food pantry list** | Name and address of each food-assistance site in the Greater Boston Food Bank (GBFB) network | [GBFB Partner Agency Locator](https://www.gbfb.org/need-food/), read 2026-11-11 |

All files were downloaded on 2026-11-11 (census blocks: 2026-11-25) and are kept unchanged
in `data/raw/`. The census-block file covers all of Massachusetts and is 102 MB, too large for
GitHub, so only its Suffolk rows and the columns used here are kept, in
`data/raw/tiger_block/suffolk_blocks_2020.csv`. `build_data.py` recreates that file from the
zip if it is missing.

> `Food Pantries in Suffolk County.pdf` in the project folder lists pantries in **Suffolk
> County, New York**, not Massachusetts, so it was not used.

---

## Step by step

### Step 1: Count the people in need
*Input: Census poverty table. Code: `load_acs()`.*

- Read the table. It has a second header row of labels, which was skipped, and an empty
  last column, which was dropped.
- Gave each block group a 12-digit ID (`GEOID`, e.g. `250250001011`) so it can be linked
  to its map shape.
- Calculated three measures of "people to serve". The team still has to choose one.

  | Column | Meaning | Income bands added |
  |---|---|---|
  | `h_total` | Everyone | all |
  | `h_pov100` | People **below the poverty line** | under 0.50 and 0.50–0.99 |
  | `h_pov185` | People below **1.85 × the poverty line** | under 0.50 up to 1.50–1.84 |
  | `moe_pov100` | Margin of error for `h_pov100` (Census formula: square root of the sum of squared margins) | |

- Block groups with nobody in them are marked `included = False`. They stay in the file
  but are left out of the model.

**Result:** 681 block groups. 17 are empty, which leaves **664 in the model**.
County totals: 740,754 people, **119,889 below the poverty line**, and
210,891 below 1.85 × the poverty line.

### Step 2: Put each block group on the map
*Input: block-group boundaries and centres of population. Code: `load_blockgroups()`.*

- **Linked the files using the block group's 12-digit ID.** Every Census file uses the
  same ID for a block group, but writes it differently:

  ```
  Census poverty table:  GEO_ID = 1500000US250250001011  →  last 12 digits  →  250250001011

  Centres file:          STATEFP  COUNTYFP  TRACTCE  BLKGRPCE
                            25   +   025   + 000101 +    1      →  250250001011
  ```

  | Part of the ID | Meaning |
  |---|---|
  | `25` | state (Massachusetts) |
  | `025` | county (Suffolk) |
  | `000101` | census tract 1.01 |
  | `1` | block group 1 within that tract |

  The block-group shapes file carries the same ID in a `GEOID` column. The centres file
  covers all of Massachusetts (5,116 block groups). Keeping county `025` leaves
  681, and these match the poverty table one-to-one.

- **Converted everything to metres.** All map data is converted to the Massachusetts state
  map projection (EPSG:26986). This is a flat grid measured in metres, so distances can be
  calculated directly.
- **Chose a centre point** (`x_i, y_i`) for each block group. Two options were calculated:
  - (a) the geometric middle of the shape;
  - (b) the Census *centre of population*, which is where the residents are on average.

  Option (b) is used because it reflects where people actually live. Option (a) is used
  only for the 10 block groups that had no residents in 2020. Both
  are kept in the file.

#### How the Census calculates the centre of population

A block group is made up of smaller **census blocks**, often a single city block. For
each block $b$, the Census has its 2020 population $w_b$ and one reference point inside
it, at latitude $\phi_b$ and longitude $\lambda_b$. The block group's centre is the
**population-weighted average** of those points:

$$\bar\phi = \frac{\sum_b w_b\,\phi_b}{\sum_b w_b} \qquad \bar\lambda = \frac{\sum_b w_b\,\lambda_b\cos\phi_b}{\sum_b w_b\cos\phi_b}$$

In words: multiply each block's latitude by its population, add these up, and divide by
the total population. Longitude works the same way with a $\cos\phi$ factor, because
lines of longitude get closer together further north. Blocks with more residents pull the
centre towards them, and empty blocks (parks, rail yards, water) don't pull at all.

The weights are **block populations, not individual addresses**. The reference point in
each block is placed by computer and does not reflect where people live inside the block.
Source: [Census Bureau, *Centers of Population Computation 1950–2020*](https://www2.census.gov/geo/pdfs/reference/cenpop2020/COP2020_documentation.pdf).

#### Worked example: block group 250250001011

| | Value |
|---|---|
| Name | Block Group 1; Census Tract 1.01; Suffolk County; Massachusetts |
| Row in the poverty table | `GEO_ID` = `1500000US250250001011` → ID `250250001011`; people counted = 755, of whom 133 are below the poverty line |
| Row in the centres file | `25,025,000101,1,1052,+42.361734,-071.133036` → ID `250250001011` |
| Meaning | 1,052 residents in 2020; their population-weighted centre is at latitude 42.361734, longitude -71.133036 |
| Converted to metres (EPSG:26986) | `x_i` = 230,229 m east, `y_i` = 901,313 m north |

This `(x_i, y_i)` is the point that all of this block group's distances (Step 6) are
measured from, and it matches the value stored in `blockgroups.geojson`.

The two population figures differ (755 vs 1,052)
because they measure different things. The poverty table counts only people whose poverty
status can be determined. That leaves out, for example, students in college dormitories
and people in institutions. It also covers 2020–2024 rather than the 2020 Census day. The
centres file is used only for *where* people are. The *number* in need always comes from
the poverty table.

**Result:** all 681 block groups matched a shape. 14 centres fall just outside
their own shape (10 of them by less than 100 m). This can happen with oddly shaped areas.
They are circled on the QA map.

### Step 2b: Spread each block group's people over its census blocks
*Input: block groups from Step 2, census blocks. Code: `load_blocks()`.*

Poverty counts are only published for whole block groups. Instead of putting all of a
block group's people at one centre point, they are shared out over the **census blocks**
inside it, in proportion to where people lived in 2020:

$$h_b = h_g \cdot \frac{P_b}{\sum_{b' \in g} P_{b'}}$$

where $h_g$ is a block group's count (`h_total`, `h_pov100` or `h_pov185`) and
$P_b$ is the 2020 population (`POP20`) of block $b$ in it. Each block's demand sits at the
Census internal point of that block.

- The census-block file covers 7,280 blocks in Suffolk, 5,549
  of them with residents. Blocks with nobody living in them get no demand.
- A block's ID is its block group's 12-digit ID plus 3 more digits, so linking is direct.
- Blocks in the 17 empty block groups (Step 1) are dropped with their block group.
- 1 block group(s) have people in the poverty table but no residents in any of their
  blocks in 2020 (`250259801011`, 27 below poverty). There is nothing to share by, so each keeps one demand point
  at a spot inside its own shape.

**Result:** **5,537 demand points** (5,536 blocks + 1 block-group point(s)).
A block group is typically split into 7 points (between 1 and
33). The block counts add back up to the block-group counts exactly, so the county
totals are unchanged. Counts per block are fractions of a person, which is fine for the model.

The block-group centres from Step 2 are still kept in `blockgroups.geojson` and used by the
interactive optimiser page (`app/`), which stays at block-group level to keep its solves fast.

### Step 3: Draw the county's land
*Input: block-group shapes, water areas, county boundary. Code: `build_land()`.*

- Merged all block-group shapes into one county outline. It matches the official county
  boundary exactly (311.36 km² including water).
- Removed 200 water features (Boston Harbor, rivers, ponds). That leaves
  **150.83 km² of land**, in line with the Census figure of
  150.89 km².
- Flagged 19 block groups in tracts numbered 98xx (Logan
  Airport, large parks and similar areas). They are not removed. Grid points there are
  marked so the team can exclude them later if it wants to.

### Step 4: Find the existing food pantries
*Input: GBFB Partner Agency Locator. Code: `src/prepare_pantries.py`, then `load_pantries()`.*

1. Searched the GBFB locator from ZIP 02119 (Roxbury) with a 10-mile radius, which covers
   the whole county. It returned **173 sites**, which were saved exactly as shown in
   `data/raw/pantries/gbfb_locator_raw.tsv`.
2. Kept only sites in Suffolk County (Boston and its neighbourhoods, Chelsea, Revere and
   Winthrop). That leaves **111 listings**.
3. Removed notes that are not part of the street address, such as "Yawkey Building
   Basement" or "at the outside window", so the addresses can be looked up.
4. Merged listings that share an address, since they are one physical location. That leaves
   **107 sites** (`data/raw/pantries/pantries_input.csv`).
5. Turned each address into map coordinates with the free Census Geocoder:
   **107 of 107 found**, all inside the county.
6. Numbered the pantries 1 to 107.

Pantry **capacity is not published**, so it is left blank and must be supplied or assumed
by the team.

### Step 5: Lay out possible new pantry sites
*Input: the land outline from Step 3. Code: `make_grid(delta_m)`.*

- Placed a point every Δ metres across the county and kept only the points that fall on land.
- Numbered the points after the existing pantries (starting at 108) and recorded which
  block group each point is in.
- The grids are nested: every 1000 m point is also a 500 m point, and every 500 m point is
  also a 250 m point. This makes results comparable across spacings.

| Spacing Δ | Number of sites | ID range | In airport/park areas |
|---|---|---|---|
| 1000 m | 154 | 108 – 261 | 33 |
| 500 m | 617 | 108 – 724 | 116 |
| 250 m | 2,429 | 108 – 2536 | 445 |

### Step 6: Measure distances
*Input: block demand points (Step 2b), block-group centres (Step 2), pantries (Step 4),
grid (Step 5). Code: `distances()`.*

- Measured the straight-line distance from each demand point to every existing pantry and
  every grid point.
- Kept only pairs closer than **3 km** (`D_max`, which can be changed with
  `--dmax`). These are the sites a demand point can "reach".

**Census blocks (used by the model, `distances_blocks_*.parquet`):**

| Spacing Δ | Pairs kept | Fewest sites reachable | Typical (median) | Most | Blocks with none |
|---|---|---|---|---|---|
| 1000 m | 209,620 | 2 | 36 | 82 | none |
| 500 m | 526,266 | 7 | 95 | 166 | none |
| 250 m | 1,777,361 | 27 | 324 | 500 | none |

**Block-group centres (used by the interactive page, `distances_*.parquet`):**

| Spacing Δ | Pairs kept | Fewest sites reachable | Typical (median) | Most | Block groups with none |
|---|---|---|---|---|---|
| 1000 m | 26,518 | 4 | 39 | 82 | none |
| 500 m | 64,875 | 9 | 98 | 165 | none |
| 250 m | 216,358 | 35 | 327 | 500 | none |

### Step 7: Draw maps
*Code: `src/plot_map.py`.*

- `poverty_map_1000.png`, `poverty_map_500.png`, `poverty_map_250.png`: red circles, one per
  census block (size = people below the poverty line in that block), green dots (existing pantries), grey dots (candidate
  sites) and block-group boundaries. Any spacing can be drawn with `--delta`, or adjusted
  live with a slider using `--interactive`.
- `qa_map.png`: block groups shaded by people below the poverty line, with the block demand
  points, the 500 m grid, pantries and the county outline. Use it to check that no site sits
  on water and that the demand points look sensible.

---

## Output files

| File | One row per | What's in it |
|---|---|---|
| `blockgroups.geojson` | block group | `GEOID`, name, the four people counts, centre `x_i, y_i` (metres), `included`, shape |
| `demand_blocks.csv` | demand point (populated census block) | `i` (15-digit block ID, or the block-group ID for a fallback point), block group `GEOID`, `x_i, y_i` (metres), `lon, lat`, 2020 block population `pop_block`, its `share` of the block group, the three people counts, `source` (`block` or `bg_point`) |
| `county_land.geojson` | n/a | The county land outline (water removed) |
| `county_land_outline.csv` | outline vertex | The same outline as plain `X, Y` (metres), one ring after another separated by an empty row, for plotting (e.g. in the Julia notebook) |
| `pantries.csv` | existing pantry | ID `j`, name, address, coordinates `X, Y` (metres) and `lon, lat`, `capacity` (blank), geocoder result |
| `grid_1000.csv`, `grid_500.csv`, `grid_250.csv` | candidate site | ID `j`, `X, Y` (metres), `lon, lat`, containing block group `GEOID`, `special_area` flag |
| `distances_blocks_1000.parquet`, `_500`, `_250` | demand point–site pair within reach | `i` (ID from `demand_blocks.csv`), `j` (site ID), `d_ij` (metres) |
| `distances_1000.parquet`, `distances_500.parquet`, `distances_250.parquet` | block group–site pair within reach | `i` (block group GEOID), `j` (site ID), `d_ij` (metres) |
| `*.png` | n/a | Maps from Step 7 |
| `checks.md` | n/a | Full technical log of every check |

`X, Y, x_i, y_i` are in metres (EPSG:26986). `lon, lat` are ordinary GPS coordinates. The
GeoJSON files are stored in GPS coordinates, so convert them back to EPSG:26986 before
measuring anything.

---

## Checks

| Check | Expected | Result | OK? |
|---|---|---|---|
| Census table has the expected number of block groups | 681 | 681 | Yes |
| The 7 income bands add up to the total in every row | all rows | all rows | Yes |
| Block groups with nobody in them | about 17 | 17 | Yes |
| Total people / below poverty / below 1.85× poverty | 740,754 / 119,889 / 210,891 | 740,754 / 119,889 / 210,891 | Yes |
| Every block group in the table has a map shape (and vice versa) | all match | all match | Yes |
| County outline built from block groups matches the official outline | same area | difference 0.0 km² | Yes |
| Land area after removing water vs Census land area | ≈ 150.89 km² | 150.83 km² | Yes |
| Every candidate site lies inside a block group | all | all | Yes |
| Pantry addresses found by the geocoder | 107 | 107 | Yes |
| Pantries located inside the county | 107 | 107 | Yes |
| Every block group has at least one site within reach | all | all | Yes |
| Block populations add up to each block group's 2020 population | all 681 | all 681 | Yes |
| Every block point lies inside its own block group | all | all | Yes |
| Block demand adds back up to each block group's counts | exact | exact | Yes |
| Every block demand point has at least one site within reach | all | all | Yes |

---

## Assumptions

1. **People in need are spread like the 2020 population within each block group.**
   Poverty counts aren't published below block-group level, so each block's share of the
   block group's people in need is assumed equal to its share of all residents in 2020
   (Step 2b). Poverty is often concentrated in particular buildings, so this is an
   approximation, but it is closer than putting everyone at one centre point.
2. **Census estimates are taken at face value.** The poverty counts are survey estimates
   with large margins of error (see `moe_pov100`). They are used as exact numbers.
3. **Travel distance is straight-line distance**, capped at 3 km. Real walking
   or transit trips are longer, especially across water, highways and rail lines.
4. **The existing pantries are the GBFB network.** Independent pantries (e.g. in Winthrop)
   are missing. Every GBFB site counts, including meal programmes and mobile markets.

## Decisions still open

- **Which people count as "in need":** `h_pov100` (below the poverty line) or `h_pov185`
  (below 1.85 × the poverty line). Confirm against the pantries' actual eligibility rules.
- **Pantry capacities:** unknown for all 107 existing pantries, and needed for new ones.
- **Model settings:** grid spacing Δ, maximum distance `D_max`, the maximum number of new
  pantries `K`, and the penalty `q` for each person left unserved.

---

## How to rebuild

Run from the project folder:

```
.venv/Scripts/python.exe -I src/prepare_pantries.py   # Step 4, parts 2–4
.venv/Scripts/python.exe -I src/build_data.py         # Steps 1–6 (writes this README)
.venv/Scripts/python.exe -I src/plot_map.py           # Step 7
.venv/Scripts/python.exe -I -u src/sweeps.py          # q and K sweeps on block demand
```
