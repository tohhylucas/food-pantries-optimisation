"""Build the geographic model data for the Suffolk County, MA food-pantry
facility-location model (handover TODOs 1-7).

Run from the project root:
    .venv/Scripts/python.exe -I src/build_data.py [--dmax 3000]

All distances are computed in EPSG:26986 (NAD83 / Massachusetts Mainland, metres).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

CRS_M = "EPSG:26986"   # metres, used for every distance / area
CRS_LL = "EPSG:4326"   # lon/lat, for export only

ACS_CSV = RAW / "acs" / "ACSDT5Y2024.C17002-Data.csv"
BG_ZIP = RAW / "tiger_bg" / "tl_2024_25_bg.zip"
WATER_ZIP = RAW / "tiger_water" / "tl_2024_25025_areawater.zip"
COUNTY_ZIP = RAW / "tiger_county" / "tl_2024_us_county.zip"
CENPOP_TXT = RAW / "cenpop" / "CenPop2020_Mean_BG25.txt"
BLOCK_ZIP = RAW / "tiger_block" / "tl_2020_25_tabblock20.zip"   # 102 MB, not in git
BLOCK_CSV = RAW / "tiger_block" / "suffolk_blocks_2020.csv"     # Suffolk extract of BLOCK_ZIP
BLOCK_KEEP = ["GEOID20", "POP20", "HOUSING20", "INTPTLAT20", "INTPTLON20", "ALAND20", "AWATER20"]
DEMAND_COLS = ["h_total", "h_pov100", "h_pov185"]
PANTRY_IN = RAW / "pantries" / "pantries_input.csv"

DELTAS = [1000, 500, 250, 100]

# Collected check results, written into README.md at the end.
REPORT: dict[str, object] = {}


def log(key: str, value) -> None:
    REPORT[key] = value
    print(f"[{key}] {value}")


# --------------------------------------------------------------------------- #
# TODO 1 - ACS C17002
# --------------------------------------------------------------------------- #
def load_acs() -> pd.DataFrame:
    df = pd.read_csv(ACS_CSV, skiprows=[1], dtype=str, encoding="utf-8-sig")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]  # trailing comma column
    df["GEOID"] = df["GEO_ID"].str[-12:]

    num_cols = [c for c in df.columns if c.startswith("C17002_")]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    E = lambda k: df[f"C17002_{k:03d}E"]  # noqa: E731
    M = lambda k: df[f"C17002_{k:03d}M"]  # noqa: E731
    df["h_total"] = E(1)
    df["h_pov100"] = E(2) + E(3)
    df["h_pov185"] = E(2) + E(3) + E(4) + E(5) + E(6)
    df["moe_pov100"] = np.sqrt(M(2) ** 2 + M(3) ** 2)
    df["moe_pov185"] = np.sqrt(sum(M(k) ** 2 for k in range(2, 7)))
    df["included"] = df["h_total"] > 0

    log("acs_rows", len(df))
    log("acs_rows_expected_681", len(df) == 681)
    log("acs_non_numeric_cells", int(df[num_cols].isna().sum().sum()))
    band_sum = sum(E(k) for k in range(2, 9))
    bad = df.loc[band_sum != E(1), "GEOID"].tolist()
    log("acs_band_sum_mismatches", bad if bad else "none (all 681 rows OK)")
    log("acs_rows_h_total_zero", int((~df["included"]).sum()))
    totals = {c: int(df[c].sum()) for c in ["h_total", "h_pov100", "h_pov185"]}
    log("acs_totals", totals)
    expected = {"h_total": 740754, "h_pov100": 119889, "h_pov185": 210891}
    log("acs_totals_match_expected", totals == expected)
    return df


# --------------------------------------------------------------------------- #
# TODO 2 - block-group polygons and centres
# --------------------------------------------------------------------------- #
def load_blockgroups(acs: pd.DataFrame) -> gpd.GeoDataFrame:
    bg = gpd.read_file(BG_ZIP)
    bg = bg[bg["COUNTYFP"] == "025"].to_crs(CRS_M)
    log("tiger_bg_rows_suffolk", len(bg))

    acs_ids, tiger_ids = set(acs["GEOID"]), set(bg["GEOID"])
    log("geoid_in_acs_not_tiger", sorted(acs_ids - tiger_ids) or "none")
    log("geoid_in_tiger_not_acs", sorted(tiger_ids - acs_ids) or "none")

    gdf = bg[["GEOID", "ALAND", "AWATER", "geometry"]].merge(
        acs[["GEOID", "NAME", "h_total", "h_pov100", "h_pov185", "moe_pov100", "moe_pov185",
             "included"]],
        on="GEOID", how="inner",
    )
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=CRS_M)
    gdf = gdf.rename(columns={"NAME": "name"})

    # (a) polygon centroid
    cen = gdf.geometry.centroid
    gdf["x_centroid"], gdf["y_centroid"] = cen.x, cen.y

    # (b) 2020 population-weighted centre of population
    cp = pd.read_csv(CENPOP_TXT, dtype=str, encoding="utf-8-sig")
    cp = cp[cp["COUNTYFP"] == "025"].copy()
    cp["GEOID"] = cp["STATEFP"] + cp["COUNTYFP"] + cp["TRACTCE"] + cp["BLKGRPCE"]
    cp_pts = gpd.GeoDataFrame(
        cp[["GEOID", "POPULATION"]],
        geometry=gpd.points_from_xy(cp["LONGITUDE"].astype(float), cp["LATITUDE"].astype(float)),
        crs="EPSG:4269",
    ).to_crs(CRS_M)
    cp_pts["x_cenpop"], cp_pts["y_cenpop"] = cp_pts.geometry.x, cp_pts.geometry.y
    cp_pts["pop2020"] = cp_pts["POPULATION"].astype(int)
    gdf = gdf.merge(cp_pts[["GEOID", "x_cenpop", "y_cenpop", "pop2020"]], on="GEOID", how="left")
    log("cenpop_missing_for_bg", gdf.loc[gdf["x_cenpop"].isna(), "GEOID"].tolist() or "none")

    # A CenPop centre for a zero-population BG is just a placeholder; use the centroid.
    use_cp = gdf["x_cenpop"].notna() & (gdf["pop2020"] > 0)
    gdf["x_i"] = np.where(use_cp, gdf["x_cenpop"], gdf["x_centroid"])
    gdf["y_i"] = np.where(use_cp, gdf["y_cenpop"], gdf["y_centroid"])
    gdf["center_source"] = np.where(use_cp, "cenpop2020", "centroid")
    log("center_source_counts", gdf["center_source"].value_counts().to_dict())

    centers = gpd.GeoSeries(gpd.points_from_xy(gdf["x_i"], gdf["y_i"]), crs=CRS_M)
    inside = centers.within(gdf.geometry.reset_index(drop=True)) | centers.touches(
        gdf.geometry.reset_index(drop=True))
    gdf["center_inside_polygon"] = inside.values
    gdf["center_dist_outside_m"] = centers.distance(gdf.geometry.reset_index(drop=True)).round(1).values
    outside = gdf.loc[~gdf["center_inside_polygon"],
                      ["GEOID", "center_source", "included", "center_dist_outside_m"]]
    log("centers_outside_own_polygon", outside.to_dict("records") or "none")
    cen_out = (~gpd.GeoSeries(gpd.points_from_xy(gdf.x_centroid, gdf.y_centroid), crs=CRS_M)
               .within(gdf.geometry.reset_index(drop=True))).sum()
    log("polygon_centroids_outside_own_polygon", int(cen_out))
    return gdf


# --------------------------------------------------------------------------- #
# Block-level demand: spread each block group's counts over its census blocks
# --------------------------------------------------------------------------- #
def load_blocks(bg: gpd.GeoDataFrame) -> pd.DataFrame:
    """One demand point per populated 2020 census block.

    Each block group's ACS counts are split over its blocks in proportion to the
    blocks' 2020 population: h_b = h_BG * POP20_b / sum(POP20 in BG). The block's
    Census internal point is its location. Block groups whose blocks had nobody in
    2020 (but people in the ACS) keep a single point at their block-group centre.
    """
    if not BLOCK_CSV.exists():
        # One-off: cut the Suffolk rows and needed columns out of the statewide TIGER file
        # (https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_25_tabblock20.zip).
        full = gpd.read_file(BLOCK_ZIP, where="COUNTYFP20='025'", ignore_geometry=True)
        full[BLOCK_KEEP].sort_values("GEOID20").to_csv(BLOCK_CSV, index=False)
    b = pd.read_csv(BLOCK_CSV, dtype={"GEOID20": str, "INTPTLAT20": str, "INTPTLON20": str})
    b["GEOID"] = b["GEOID20"].str[:12]
    b["pop_block"] = b["POP20"].astype(int)
    log("blocks_suffolk", len(b))
    log("blocks_populated", int((b["pop_block"] > 0).sum()))

    bg_pop = bg.set_index("GEOID")["pop2020"]
    block_sum = b.groupby("GEOID")["pop_block"].sum().reindex(bg_pop.index, fill_value=0)
    log("block_pop_sum_mismatch_vs_cenpop", block_sum.index[block_sum != bg_pop].tolist() or "none")

    b = b[b["pop_block"] > 0].copy()
    pts = gpd.GeoSeries(gpd.points_from_xy(b["INTPTLON20"].astype(float), b["INTPTLAT20"].astype(float)),
                        crs="EPSG:4269").to_crs(CRS_M)
    b["x_i"], b["y_i"] = pts.x.to_numpy(), pts.y.to_numpy()

    inside = gpd.GeoSeries(pts.values, crs=CRS_M).within(
        bg.set_index("GEOID").geometry.reindex(b["GEOID"]).reset_index(drop=True))
    log("block_points_outside_own_bg", int((~inside.to_numpy()).sum()))

    dem = bg.loc[bg["included"], ["GEOID", "pop2020", "x_i", "y_i"] + DEMAND_COLS]
    d = b[["GEOID20", "GEOID", "pop_block", "x_i", "y_i"]].merge(
        dem.drop(columns=["x_i", "y_i"]), on="GEOID", how="inner")
    d["share"] = d["pop_block"] / d["pop2020"]
    for c in DEMAND_COLS:
        d[c] = d[c] * d["share"]
    d = d.rename(columns={"GEOID20": "i"})
    d["source"] = "block"

    # Fallback: one point guaranteed inside the block group's own polygon (a multi-island
    # block group's centroid can land in the water).
    fb = dem[~dem["GEOID"].isin(d["GEOID"])].copy()
    rp = bg.set_index("GEOID").geometry.reindex(fb["GEOID"]).representative_point()
    fb["x_i"], fb["y_i"] = rp.x.to_numpy(), rp.y.to_numpy()
    fb["i"], fb["pop_block"], fb["share"], fb["source"] = fb["GEOID"], 0, 1.0, "bg_point"
    log("demand_bg_without_populated_blocks",
        fb[["GEOID"] + DEMAND_COLS].to_dict("records") or "none")

    cols = ["i", "GEOID", "x_i", "y_i", "pop_block", "share"] + DEMAND_COLS + ["source"]
    out = pd.concat([d[cols], fb[cols]], ignore_index=True)
    ll = gpd.GeoSeries(gpd.points_from_xy(out["x_i"], out["y_i"]), crs=CRS_M).to_crs(CRS_LL)
    out.insert(4, "lon", ll.x.round(6).to_numpy())
    out.insert(5, "lat", ll.y.round(6).to_numpy())

    sums = out.groupby("GEOID")[DEMAND_COLS].sum()
    ref = dem.set_index("GEOID")[DEMAND_COLS].reindex(sums.index)
    log("demand_points", len(out))
    log("demand_points_by_source", out["source"].value_counts().to_dict())
    log("block_demand_sums_match_bg", bool(np.allclose(sums.to_numpy(), ref.to_numpy())
                                            and len(sums) == len(dem)))
    log("block_demand_totals", {c: round(float(out[c].sum()), 3) for c in DEMAND_COLS})
    per_bg = out.groupby("GEOID").size()
    log("demand_points_per_bg", {"min": int(per_bg.min()), "median": float(per_bg.median()),
                                 "max": int(per_bg.max())})
    return out


# --------------------------------------------------------------------------- #
# TODO 3 - county polygon and water mask
# --------------------------------------------------------------------------- #
def build_land(bg: gpd.GeoDataFrame):
    county = bg.geometry.union_all().buffer(0)

    us = gpd.read_file(COUNTY_ZIP, where="STATEFP='25' AND COUNTYFP='025'").to_crs(CRS_M)
    tiger_county = us.geometry.iloc[0]
    sym = county.symmetric_difference(tiger_county).area
    log("county_area_km2_dissolved", round(county.area / 1e6, 2))
    log("county_area_km2_tiger", round(tiger_county.area / 1e6, 2))
    log("county_symdiff_km2", round(sym / 1e6, 4))

    water = gpd.read_file(WATER_ZIP).to_crs(CRS_M)
    water_union = water.geometry.union_all().buffer(0)
    land = county.difference(water_union).buffer(0)
    log("areawater_features", len(water))
    log("land_area_km2", round(land.area / 1e6, 2))
    log("tiger_ALAND_sum_km2", round(bg["ALAND"].astype(float).sum() / 1e6, 2))

    # Special areas (tract codes 98xx: Logan Airport, parks, etc.) - flagged only.
    special = bg[bg["GEOID"].str[5:7] == "98"]
    log("special_area_bgs_98xx", special["GEOID"].tolist())
    special_geom = special.geometry.union_all() if len(special) else None
    return county, land, special_geom


# --------------------------------------------------------------------------- #
# TODO 4 - candidate grid
# --------------------------------------------------------------------------- #
def site_geoids(sites: gpd.GeoDataFrame, bg: gpd.GeoDataFrame) -> pd.Series:
    joined = gpd.sjoin(sites, bg[["GEOID", "geometry"]], how="left", predicate="intersects")
    return joined.loc[~joined.index.duplicated(keep="first"), "GEOID"]


def make_grid(delta_m: float, land, bg: gpd.GeoDataFrame, m: int = 0,
              special_geom=None) -> gpd.GeoDataFrame:
    """Candidate sites every `delta_m` metres inside the land polygon.

    IDs start at m+1 so that J_E = 1..m and J_C = m+1..m+N.
    """
    minx, miny, maxx, maxy = land.bounds
    # Anchor the lattice to multiples of delta so grids nest (250 ⊃ 500 ⊃ 1000 and
    # 100 ⊃ 500 ⊃ 1000; 100 m does not contain the 250 m grid, as 250 is not a multiple of 100).
    xs = np.arange(np.ceil(minx / delta_m) * delta_m, maxx + 1e-9, delta_m)
    ys = np.arange(np.ceil(miny / delta_m) * delta_m, maxy + 1e-9, delta_m)
    X, Y = np.meshgrid(xs, ys)
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(X.ravel(), Y.ravel()), crs=CRS_M)
    pts = pts[pts.within(land)].reset_index(drop=True)

    grid = pts.assign(GEOID=site_geoids(pts, bg))
    grid["X"], grid["Y"] = grid.geometry.x, grid.geometry.y
    ll = grid.geometry.to_crs(CRS_LL)
    grid["lon"], grid["lat"] = ll.x.round(6), ll.y.round(6)
    grid["special_area"] = grid.within(special_geom) if special_geom is not None else False
    grid.insert(0, "j", np.arange(m + 1, m + 1 + len(grid)))
    return grid


# --------------------------------------------------------------------------- #
# TODO 5 - existing pantries
# --------------------------------------------------------------------------- #
PANTRY_COLS = ["name", "address", "city", "state", "zip", "capacity"]


def census_batch_geocode(df: pd.DataFrame) -> pd.DataFrame:
    """Census Geocoder batch service (<=10,000 rows per request)."""
    buf = io.StringIO()
    pd.DataFrame({
        "id": df.index, "street": df["address"], "city": df["city"].fillna(""),
        "state": df["state"].fillna("MA"), "zip": df["zip"].fillna(""),
    }).to_csv(buf, header=False, index=False)
    r = requests.post(
        "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
        files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
        data={"benchmark": "Public_AR_Current"}, timeout=300,
    )
    r.raise_for_status()
    res = pd.read_csv(io.StringIO(r.text), header=None, dtype=str,
                      names=["id", "input", "match", "match_type", "matched_address",
                             "lonlat", "tiger_line_id", "side"])
    res["id"] = res["id"].astype(int)
    return res.set_index("id")


def load_pantries(county=None) -> gpd.GeoDataFrame:
    cols = ["j", "name", "address", "city", "zip", "X", "Y", "lon", "lat", "capacity",
            "geocode_status", "matched_address", "in_county", "gbfb_idx", "source"]
    if not PANTRY_IN.exists():
        PANTRY_IN.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=PANTRY_COLS).to_csv(PANTRY_IN, index=False)
    src = pd.read_csv(PANTRY_IN, dtype=str)
    for c in PANTRY_COLS + ["gbfb_idx", "source"]:
        if c not in src.columns:
            src[c] = pd.NA

    if src.empty:
        log("pantries", "PLACEHOLDER - data/raw/pantries/pantries_input.csv has no rows; m = 0")
        return gpd.GeoDataFrame(columns=cols, geometry=[], crs=CRS_M)

    res = census_batch_geocode(src)
    # Retry unmatched rows without the ZIP (some listings carry a wrong ZIP).
    miss = res.index[res["match"] != "Match"].intersection(src.index)
    if len(miss):
        retry = census_batch_geocode(src.loc[miss].assign(zip=""))
        hit = retry.index[retry["match"] == "Match"]
        res.loc[hit] = retry.loc[hit].assign(match="Match (retry without ZIP)")
        log("pantries_geocoded_on_retry_without_zip",
            src.loc[hit, ["name", "address", "zip"]].to_dict("records") or "none")
    src["geocode_status"] = res["match"].reindex(src.index).fillna("No_Response")
    src["matched_address"] = res["matched_address"].reindex(src.index)
    lonlat = res["lonlat"].reindex(src.index).str.split(",", expand=True)
    src["lon"] = pd.to_numeric(lonlat[0], errors="coerce")
    src["lat"] = pd.to_numeric(lonlat[1], errors="coerce")
    failed = src.loc[src["lon"].isna(), ["name", "address", "city", "geocode_status"]]
    log("pantries_input_rows", len(src))
    log("pantries_geocode_failed", failed.to_dict("records") or "none")

    ok = src[src["lon"].notna()].reset_index(drop=True)
    g = gpd.GeoDataFrame(ok, geometry=gpd.points_from_xy(ok["lon"], ok["lat"]),
                         crs="EPSG:4269").to_crs(CRS_M)
    g["X"], g["Y"] = g.geometry.x, g.geometry.y
    g["lon"], g["lat"] = g["lon"].round(6), g["lat"].round(6)
    g["in_county"] = g.within(county) if county is not None else True
    outside = g.loc[~g["in_county"], ["name", "address", "matched_address"]]
    log("pantries_geocoded_outside_county", outside.to_dict("records") or "none")
    g = g[g["in_county"]].reset_index(drop=True)
    g["capacity"] = pd.to_numeric(g["capacity"], errors="coerce")
    g["j"] = np.arange(1, len(g) + 1)
    log("pantries_m", len(g))
    log("pantries_missing_capacity", int(g["capacity"].isna().sum()))
    return g[cols + ["geometry"]]


# --------------------------------------------------------------------------- #
# TODO 6 - distances and reachable sets
# --------------------------------------------------------------------------- #
def distances(ids, x, y, sites: pd.DataFrame, dmax: float, chunk: int = 500) -> pd.DataFrame:
    """All (demand point i, site j) pairs within dmax metres.

    Demand points are processed in chunks so the full distance matrix is never held
    in memory (the 100 m grid has ~15,000 sites).
    """
    ids, x, y = np.asarray(ids), np.asarray(x, float), np.asarray(y, float)
    sx, sy = sites["X"].to_numpy(float), sites["Y"].to_numpy(float)
    sj = sites["j"].to_numpy().astype(int)
    parts = []
    for s in range(0, len(x), chunk):
        d = np.hypot(x[s:s + chunk, None] - sx[None, :], y[s:s + chunk, None] - sy[None, :])
        ii, jj = np.nonzero(d <= dmax)
        parts.append(pd.DataFrame({"i": ids[s:s + chunk][ii], "j": sj[jj],
                                   "d_ij": d[ii, jj].round(1)}))
    return pd.concat(parts, ignore_index=True)


def reachable_report(dist: pd.DataFrame, ids) -> dict:
    sizes = dist.groupby("i").size().reindex(pd.Index(ids), fill_value=0)
    return {
        "pairs": len(dist),
        "A_i_min": int(sizes.min()), "A_i_median": float(sizes.median()),
        "A_i_max": int(sizes.max()),
        "empty_A_i": sizes[sizes == 0].index.tolist() or "none",
    }


# --------------------------------------------------------------------------- #
# TODO 7 - outputs
# --------------------------------------------------------------------------- #
def write_checks_log() -> None:
    """Full machine-style check log (every value logged during the run)."""
    def fmt(v):
        return json.dumps(v, default=str) if not isinstance(v, str) else v

    lines = ["# Full check log", "",
             f"Every value recorded by `src/build_data.py` on {date.today().isoformat()}. "
             "See README.md for the plain-language summary.", ""]
    lines += [f"- **{k}**: {fmt(v)}" for k, v in REPORT.items()]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(dmax: float) -> None:
    """Plain-language README: inputs, each processing step, outputs, checks."""
    R = REPORT
    yes = lambda b: "Yes" if b else "**No**"  # noqa: E731
    tot = R["acs_totals"]
    n_bg, n_empty = R["acs_rows"], R["acs_rows_h_total_zero"]
    cs = R["center_source_counts"]
    outside = R["centers_outside_own_polygon"]
    outside = outside if isinstance(outside, list) else []
    near = sum(o["center_dist_outside_m"] < 100 for o in outside)
    m = R.get("pantries_m", 0)

    raw_path = PANTRY_IN.parent / "gbfb_locator_raw.tsv"
    n_raw = len(pd.read_csv(raw_path, sep="\t")) if raw_path.exists() else 0
    pin = pd.read_csv(PANTRY_IN) if PANTRY_IN.exists() else pd.DataFrame()
    n_listings = int(pin["n_listings"].sum()) if "n_listings" in pin else len(pin)

    # Worked example: trace one block group through both Census files.
    ex_id = "250250001011"
    acs_raw = pd.read_csv(ACS_CSV, skiprows=[1], dtype=str, encoding="utf-8-sig")
    ex_acs = acs_raw[acs_raw["GEO_ID"].str[-12:] == ex_id].iloc[0]
    cp_all = pd.read_csv(CENPOP_TXT, dtype=str, encoding="utf-8-sig")
    cp_ids = cp_all["STATEFP"] + cp_all["COUNTYFP"] + cp_all["TRACTCE"] + cp_all["BLKGRPCE"]
    n_cp_suffolk = int((cp_all["COUNTYFP"] == "025").sum())
    ex_cp = cp_all[cp_ids == ex_id].iloc[0]
    ex_lat, ex_lon = float(ex_cp["LATITUDE"]), float(ex_cp["LONGITUDE"])
    ex_xy = gpd.GeoSeries(gpd.points_from_xy([ex_lon], [ex_lat]), crs="EPSG:4269").to_crs(CRS_M)
    ex_x, ex_y = ex_xy.x.iloc[0], ex_xy.y.iloc[0]
    # Census mean-centre formula (kept out of the f-string because of the LaTeX braces).
    block_formula = r"$$h_b = h_g \cdot \frac{P_b}{\sum_{b' \in g} P_{b'}}$$"
    formula = (r"$$\bar\phi = \frac{\sum_b w_b\,\phi_b}{\sum_b w_b} \qquad "
               r"\bar\lambda = \frac{\sum_b w_b\,\lambda_b\cos\phi_b}{\sum_b w_b\cos\phi_b}$$")

    grid_rows = "\n".join(
        f"| {d} m | {R[f'grid_{d}_N']:,} | {m + 1} – {m + R[f'grid_{d}_N']} | "
        f"{R[f'grid_{d}_special_area']} |" for d in DELTAS)
    reach_b_rows = "\n".join(
        f"| {d} m | {R[f'reach_blocks_{d}']['pairs']:,} | {R[f'reach_blocks_{d}']['A_i_min']} | "
        f"{R[f'reach_blocks_{d}']['A_i_median']:g} | {R[f'reach_blocks_{d}']['A_i_max']} | "
        f"{R[f'reach_blocks_{d}']['empty_A_i'] if R[f'reach_blocks_{d}']['empty_A_i'] != 'none' else 'none'} |"
        for d in DELTAS)
    nb_src = R["demand_points_by_source"]
    n_blk, n_fb = nb_src.get("block", 0), nb_src.get("bg_point", 0)
    fb_list = R["demand_bg_without_populated_blocks"]
    fb_list = fb_list if isinstance(fb_list, list) else []
    fb_text = ", ".join(f"`{f['GEOID']}`, {f['h_pov100']} below poverty" for f in fb_list) or "none"
    ppb = R["demand_points_per_bg"]
    reach_rows = "\n".join(
        f"| {d} m | {R[f'reach_{d}']['pairs']:,} | {R[f'reach_{d}']['A_i_min']} | "
        f"{R[f'reach_{d}']['A_i_median']:g} | {R[f'reach_{d}']['A_i_max']} | "
        f"{R[f'reach_{d}']['empty_A_i'] if R[f'reach_{d}']['empty_A_i'] != 'none' else 'none'} |"
        for d in DELTAS)

    expected_tot = {"h_total": 740754, "h_pov100": 119889, "h_pov185": 210891}
    bg_match = R["geoid_in_acs_not_tiger"] == "none" and R["geoid_in_tiger_not_acs"] == "none"
    grid_ok = all(R[f"grid_{d}_no_geoid"] == 0 for d in DELTAS)
    reach_ok = all(R[f"reach_{d}"]["empty_A_i"] == "none" for d in DELTAS)
    reach_b_ok = all(R[f"reach_blocks_{d}"]["empty_A_i"] == "none" for d in DELTAS)
    blk_pop_ok = R["block_pop_sum_mismatch_vs_cenpop"] == "none"
    blk_sum_ok = bool(R["block_demand_sums_match_bg"])
    blk_out = R["block_points_outside_own_bg"]
    geo_ok = R.get("pantries_geocode_failed") == "none"
    in_ok = R.get("pantries_geocoded_outside_county") == "none"
    bands_ok = str(R["acs_band_sum_mismatches"]).startswith("none")
    checks = [
        ("Census table has the expected number of block groups", "681", f"{n_bg}",
         n_bg == 681),
        ("The 7 income bands add up to the total in every row", "all rows",
         "all rows" if bands_ok else "some rows fail", bands_ok),
        ("Block groups with nobody in them", "about 17", f"{n_empty}", 15 <= n_empty <= 20),
        ("Total people / below poverty / below 1.85× poverty",
         " / ".join(f"{v:,}" for v in expected_tot.values()),
         " / ".join(f"{v:,}" for v in tot.values()), tot == expected_tot),
        ("Every block group in the table has a map shape (and vice versa)", "all match",
         "all match" if bg_match else "mismatches", bg_match),
        ("County outline built from block groups matches the official outline", "same area",
         f"difference {R['county_symdiff_km2']} km²", R["county_symdiff_km2"] < 0.01),
        ("Land area after removing water vs Census land area",
         f"≈ {R['tiger_ALAND_sum_km2']} km²", f"{R['land_area_km2']} km²",
         abs(R["land_area_km2"] - R["tiger_ALAND_sum_km2"]) < 1),
        ("Every candidate site lies inside a block group", "all",
         "all" if grid_ok else "some outside", grid_ok),
        ("Pantry addresses found by the geocoder", f"{len(pin)}",
         f"{m}" if geo_ok else "some failed", geo_ok),
        ("Pantries located inside the county", f"{m}",
         f"{m}" if in_ok else "some outside", in_ok),
        ("Every block group has at least one site within reach", "all",
         "all" if reach_ok else "some have none", reach_ok),
        ("Block populations add up to each block group's 2020 population", "all 681",
         "all 681" if blk_pop_ok else "some differ", blk_pop_ok),
        ("Every block point lies inside its own block group", "all",
         "all" if blk_out == 0 else f"{blk_out} outside", blk_out == 0),
        ("Block demand adds back up to each block group's counts", "exact",
         "exact" if blk_sum_ok else "differs", blk_sum_ok),
        ("Every block demand point has at least one site within reach", "all",
         "all" if reach_b_ok else "some have none", reach_b_ok),
    ]
    check_rows = "\n".join(f"| {c} | {e} | {r} | {yes(b)} |" for c, e, r, b in checks)
    fence = "```"

    text = f"""# How the model data was built

This folder holds the input data for the Suffolk County, MA food-pantry location model.
This page explains **what data we started with** and **what was done to it, step by step**.

The numbers on this page are filled in automatically by `src/build_data.py` each time it
runs (last run: {date.today().isoformat()}). A full technical log of every check is in
[`checks.md`](checks.md).

---

## The short version

1. **Count the people in need.** The Census reports, for each of the county's {n_bg}
   *block groups* (small neighbourhoods), how many people live below the poverty line.
2. **Put each block group on the map, then spread its people over its census blocks.** Each
   block group gets its boundary shape. Its people in need are then shared out over the
   census blocks inside it, in proportion to each block's 2020 population, so demand sits
   at {n_blk + n_fb:,} block points instead of {n_bg - n_empty} block-group centres.
3. **Draw the county's land.** Merge the shapes into one outline and remove harbour, river
   and pond water.
4. **Find the existing food pantries.** {m} sites were collected from the Greater Boston
   Food Bank's online locator, and their addresses were turned into map coordinates.
5. **Lay out possible new pantry sites.** A regular grid of points is placed over the land,
   one every 1000 m, 500 m, 250 m or 100 m.
6. **Measure distances.** The distance is measured from every demand point (census block)
   to every pantry or grid point within {dmax / 1000:g} km.
7. **Draw maps** to check that everything looks right.

{fence}
Census poverty table ─┐
Block-group shapes ───┼─► block groups with people counts + centres ─┐
Population centres ───┤                                               │
Census blocks ────────┴─► people in need per census block ────────────┤
Water areas ─────────────► county land outline ─► candidate grid ─────┼─► distances ─► maps
GBFB pantry locator ─────► cleaned pantry list ─► geocoded pantries ──┘
{fence}

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
  | `moe_pov185` | Margin of error for `h_pov185`, same formula over the same five bands | |

- Block groups with nobody in them are marked `included = False`. They stay in the file
  but are left out of the model.

**Result:** {n_bg} block groups. {n_empty} are empty, which leaves **{n_bg - n_empty} in the model**.
County totals: {tot['h_total']:,} people, **{tot['h_pov100']:,} below the poverty line**, and
{tot['h_pov185']:,} below 1.85 × the poverty line.

### Step 2: Put each block group on the map
*Input: block-group boundaries and centres of population. Code: `load_blockgroups()`.*

- **Linked the files using the block group's 12-digit ID.** Every Census file uses the
  same ID for a block group, but writes it differently:

  {fence}
  Census poverty table:  GEO_ID = 1500000US250250001011  →  last 12 digits  →  250250001011

  Centres file:          STATEFP  COUNTYFP  TRACTCE  BLKGRPCE
                            25   +   025   + 000101 +    1      →  250250001011
  {fence}

  | Part of the ID | Meaning |
  |---|---|
  | `25` | state (Massachusetts) |
  | `025` | county (Suffolk) |
  | `000101` | census tract 1.01 |
  | `1` | block group 1 within that tract |

  The block-group shapes file carries the same ID in a `GEOID` column. The centres file
  covers all of Massachusetts ({len(cp_all):,} block groups). Keeping county `025` leaves
  {n_cp_suffolk}, and these match the poverty table one-to-one.

- **Converted everything to metres.** All map data is converted to the Massachusetts state
  map projection (EPSG:26986). This is a flat grid measured in metres, so distances can be
  calculated directly.
- **Chose a centre point** (`x_i, y_i`) for each block group. Two options were calculated:
  - (a) the geometric middle of the shape;
  - (b) the Census *centre of population*, which is where the residents are on average.

  Option (b) is used because it reflects where people actually live. Option (a) is used
  only for the {cs.get('centroid', 0)} block groups that had no residents in 2020. Both
  are kept in the file.

#### How the Census calculates the centre of population

A block group is made up of smaller **census blocks**, often a single city block. For
each block $b$, the Census has its 2020 population $w_b$ and one reference point inside
it, at latitude $\\phi_b$ and longitude $\\lambda_b$. The block group's centre is the
**population-weighted average** of those points:

{formula}

In words: multiply each block's latitude by its population, add these up, and divide by
the total population. Longitude works the same way with a $\\cos\\phi$ factor, because
lines of longitude get closer together further north. Blocks with more residents pull the
centre towards them, and empty blocks (parks, rail yards, water) don't pull at all.

The weights are **block populations, not individual addresses**. The reference point in
each block is placed by computer and does not reflect where people live inside the block.
Source: [Census Bureau, *Centers of Population Computation 1950–2020*](https://www2.census.gov/geo/pdfs/reference/cenpop2020/COP2020_documentation.pdf).

#### Worked example: block group {ex_id}

| | Value |
|---|---|
| Name | {ex_acs['NAME']} |
| Row in the poverty table | `GEO_ID` = `{ex_acs['GEO_ID']}` → ID `{ex_id}`; people counted = {int(ex_acs['C17002_001E']):,}, of whom {int(ex_acs['C17002_002E']) + int(ex_acs['C17002_003E']):,} are below the poverty line |
| Row in the centres file | `{ex_cp['STATEFP']},{ex_cp['COUNTYFP']},{ex_cp['TRACTCE']},{ex_cp['BLKGRPCE']},{ex_cp['POPULATION']},{ex_cp['LATITUDE']},{ex_cp['LONGITUDE']}` → ID `{ex_id}` |
| Meaning | {int(ex_cp['POPULATION']):,} residents in 2020; their population-weighted centre is at latitude {ex_lat:.6f}, longitude {ex_lon:.6f} |
| Converted to metres (EPSG:26986) | `x_i` = {ex_x:,.0f} m east, `y_i` = {ex_y:,.0f} m north |

This `(x_i, y_i)` is the point that all of this block group's distances (Step 6) are
measured from, and it matches the value stored in `blockgroups.geojson`.

The two population figures differ ({int(ex_acs['C17002_001E']):,} vs {int(ex_cp['POPULATION']):,})
because they measure different things. The poverty table counts only people whose poverty
status can be determined. That leaves out, for example, students in college dormitories
and people in institutions. It also covers 2020–2024 rather than the 2020 Census day. The
centres file is used only for *where* people are. The *number* in need always comes from
the poverty table.

**Result:** all {n_bg} block groups matched a shape. {len(outside)} centres fall just outside
their own shape ({near} of them by less than 100 m). This can happen with oddly shaped areas.
They are circled on the QA map.

### Step 2b: Spread each block group's people over its census blocks
*Input: block groups from Step 2, census blocks. Code: `load_blocks()`.*

Poverty counts are only published for whole block groups. Instead of putting all of a
block group's people at one centre point, they are shared out over the **census blocks**
inside it, in proportion to where people lived in 2020:

{block_formula}

where $h_g$ is a block group's count (`h_total`, `h_pov100` or `h_pov185`) and
$P_b$ is the 2020 population (`POP20`) of block $b$ in it. Each block's demand sits at the
Census internal point of that block.

- The census-block file covers {R['blocks_suffolk']:,} blocks in Suffolk, {R['blocks_populated']:,}
  of them with residents. Blocks with nobody living in them get no demand.
- A block's ID is its block group's 12-digit ID plus 3 more digits, so linking is direct.
- Blocks in the {n_empty} empty block groups (Step 1) are dropped with their block group.
- {len(fb_list)} block group(s) have people in the poverty table but no residents in any of their
  blocks in 2020 ({fb_text}). There is nothing to share by, so each keeps one demand point
  at a spot inside its own shape.

**Result:** **{n_blk + n_fb:,} demand points** ({n_blk:,} blocks + {n_fb} block-group point(s)).
A block group is typically split into {ppb['median']:g} points (between {ppb['min']} and
{ppb['max']}). The block counts add back up to the block-group counts exactly, so the county
totals are unchanged. Counts per block are fractions of a person, which is fine for the model.

The block-group centres from Step 2 are still kept in `blockgroups.geojson` and used by the
interactive optimiser page (`app/`), which stays at block-group level to keep its solves fast.

### Step 3: Draw the county's land
*Input: block-group shapes, water areas, county boundary. Code: `build_land()`.*

- Merged all block-group shapes into one county outline. It matches the official county
  boundary exactly ({R['county_area_km2_tiger']} km² including water).
- Removed {R['areawater_features']} water features (Boston Harbor, rivers, ponds). That leaves
  **{R['land_area_km2']} km² of land**, in line with the Census figure of
  {R['tiger_ALAND_sum_km2']} km².
- Flagged {len(R['special_area_bgs_98xx'])} block groups in tracts numbered 98xx (Logan
  Airport, large parks and similar areas). They are not removed. Grid points there are
  marked so the team can exclude them later if it wants to.

### Step 4: Find the existing food pantries
*Input: GBFB Partner Agency Locator. Code: `src/prepare_pantries.py`, then `load_pantries()`.*

1. Searched the GBFB locator from ZIP 02119 (Roxbury) with a 10-mile radius, which covers
   the whole county. It returned **{n_raw} sites**, which were saved exactly as shown in
   `data/raw/pantries/gbfb_locator_raw.tsv`.
2. Kept only sites in Suffolk County (Boston and its neighbourhoods, Chelsea, Revere and
   Winthrop). That leaves **{n_listings} listings**.
3. Removed notes that are not part of the street address, such as "Yawkey Building
   Basement" or "at the outside window", so the addresses can be looked up.
4. Merged listings that share an address, since they are one physical location. That leaves
   **{len(pin)} sites** (`data/raw/pantries/pantries_input.csv`).
5. Turned each address into map coordinates with the free Census Geocoder:
   **{m} of {len(pin)} found**, all inside the county.
6. Numbered the pantries 1 to {m}.

Pantry **capacity is not published**, so the `capacity` column is left blank. The model
instead gives every pantry the same estimated capacity of **900 people per month**, the
Massachusetts network average (about 826,000 people served monthly through over 900
programs, MEFAP FY23 report), tested at 600 and 1,200. See the main README, Section 2.

### Step 5: Lay out possible new pantry sites
*Input: the land outline from Step 3. Code: `make_grid(delta_m)`.*

- Placed a point every Δ metres across the county and kept only the points that fall on land.
- Numbered the points after the existing pantries (starting at {m + 1}) and recorded which
  block group each point is in.
- The grids are nested: every 1000 m point is also a 500 m point, and every 500 m point is
  also a 250 m point and a 100 m point. This makes results comparable across spacings.
  (The 250 m and 100 m grids are not nested in each other, since 250 is not a multiple of 100.)

| Spacing Δ | Number of sites | ID range | In airport/park areas |
|---|---|---|---|
{grid_rows}

### Step 6: Measure distances
*Input: block demand points (Step 2b), block-group centres (Step 2), pantries (Step 4),
grid (Step 5). Code: `distances()`.*

- Measured the straight-line distance from each demand point to every existing pantry and
  every grid point.
- Kept only pairs closer than **{dmax / 1000:g} km** (`D_max`, which can be changed with
  `--dmax`). These are the sites a demand point can "reach".

**Census blocks (used by the model, `distances_blocks_*.parquet`):**

| Spacing Δ | Pairs kept | Fewest sites reachable | Typical (median) | Most | Blocks with none |
|---|---|---|---|---|---|
{reach_b_rows}

**Block-group centres (used by the interactive page, `distances_*.parquet`):**

| Spacing Δ | Pairs kept | Fewest sites reachable | Typical (median) | Most | Block groups with none |
|---|---|---|---|---|---|
{reach_rows}

### Step 7: Draw maps
*Code: `src/plot_map.py`.*

- `poverty_map_1000.png`, `_500`, `_250`, `_100`: red circles, one per
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
| `blockgroup_demand.csv` | block group | `GEOID`, `included`, `h_pov100`, `h_pov185`, `moe_pov100`, `moe_pov185`. Margins are kept at block-group level: the robust model's uncertainty is per block group, and each block's share of an increase is its `share` in `demand_blocks.csv` |
| `demand_blocks.csv` | demand point (populated census block) | `i` (15-digit block ID, or the block-group ID for a fallback point), block group `GEOID`, `x_i, y_i` (metres), `lon, lat`, 2020 block population `pop_block`, its `share` of the block group, the three people counts, `source` (`block` or `bg_point`) |
| `county_land.geojson` | n/a | The county land outline (water removed) |
| `county_land_outline.csv` | outline vertex | The same outline as plain `X, Y` (metres), one ring after another separated by an empty row, for plotting (e.g. in the Julia notebook) |
| `pantries.csv` | existing pantry | ID `j`, name, address, coordinates `X, Y` (metres) and `lon, lat`, `capacity` (blank), geocoder result, containing block group `GEOID` |
| `grid_1000.csv`, `grid_500.csv`, `grid_250.csv`, `grid_100.csv` | candidate site | ID `j`, `X, Y` (metres), `lon, lat`, containing block group `GEOID`, `special_area` flag |
| `distances_blocks_1000.parquet`, `_500`, `_250`, `_100` | demand point–site pair within reach | `i` (ID from `demand_blocks.csv`), `j` (site ID), `d_ij` (metres) |
| `distances_1000.parquet`, `_500`, `_250`, `_100` | block group–site pair within reach | `i` (block group GEOID), `j` (site ID), `d_ij` (metres) |
| `*.png` | n/a | Maps from Step 7 |
| `checks.md` | n/a | Full technical log of every check |

`X, Y, x_i, y_i` are in metres (EPSG:26986). `lon, lat` are ordinary GPS coordinates. The
GeoJSON files are stored in GPS coordinates, so convert them back to EPSG:26986 before
measuring anything.

---

## Checks

| Check | Expected | Result | OK? |
|---|---|---|---|
{check_rows}

---

## Assumptions

1. **People in need are spread like the 2020 population within each block group.**
   Poverty counts aren't published below block-group level, so each block's share of the
   block group's people in need is assumed equal to its share of all residents in 2020
   (Step 2b). Poverty is often concentrated in particular buildings, so this is an
   approximation, but it is closer than putting everyone at one centre point.
2. **Census estimates are taken at face value.** The poverty counts are survey estimates
   with large margins of error (see `moe_pov100`, `moe_pov185`). The nominal model uses them
   as exact numbers; the robust model lets them rise by up to their margin.
3. **Travel distance is straight-line distance**, capped at {dmax / 1000:g} km. Real walking
   or transit trips are longer, especially across water, highways and rail lines.
4. **The existing pantries are the GBFB network.** Independent pantries (e.g. in Winthrop)
   are missing. Every GBFB site counts, including meal programmes and mobile markets.

## Decisions still open

- **Which people count as "in need":** `h_pov100` (below the poverty line) or `h_pov185`
  (below 1.85 × the poverty line). Confirm against the pantries' actual eligibility rules.
- **Pantry capacities:** not published for any of the {m} existing pantries. The model uses a
  network-average estimate of 900 people per month for every pantry (main README, Section 2);
  replace it if GBFB shares pantry-level data.
- **Model settings:** grid spacing Δ, maximum distance `D_max`, the maximum number of new
  pantries `K`, and the penalty `q` for each person left unserved.

---

## How to rebuild

Run from the project folder:

{fence}
.venv/Scripts/python.exe -I src/prepare_pantries.py   # Step 4, parts 2–4
.venv/Scripts/python.exe -I src/build_data.py         # Steps 1–6 (writes this README)
.venv/Scripts/python.exe -I src/plot_map.py           # Step 7
.venv/Scripts/python.exe -I -u src/sweeps.py          # q and K sweeps on block demand
{fence}
"""
    (OUT / "README.md").write_text(text, encoding="utf-8")


def write_bg_demand(bg: gpd.GeoDataFrame) -> None:
    """Block-group estimates and 90% margins of error, for the robust model."""
    cols = ["GEOID", "included", "h_pov100", "h_pov185", "moe_pov100", "moe_pov185"]
    bg[cols].sort_values("GEOID").round(4).to_csv(OUT / "blockgroup_demand.csv", index=False)
    inc = bg[bg["included"]]
    for c in ["pov100", "pov185"]:
        rel = (inc[f"moe_{c}"] / inc[f"h_{c}"]).replace(np.inf, np.nan)
        log(f"moe_{c}_median_relative", round(float(rel.median()), 3))


def write_outline(geom, path: Path, tol_m: float = 5.0) -> None:
    """Land outline as plain X,Y rows (metres) for plotting without a GIS library.

    Each ring (coastline or lake shore) ends with an empty row, so plotting tools
    that break lines at missing values draw the rings separately.
    """
    geom = geom.simplify(tol_m, preserve_topology=True)
    polys = getattr(geom, "geoms", [geom])
    rows = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            rows += [(round(x, 1), round(y, 1)) for x, y in ring.coords] + [(None, None)]
    pd.DataFrame(rows, columns=["X", "Y"]).to_csv(path, index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dmax", type=float, default=3000.0)
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    acs = load_acs()
    bg = load_blockgroups(acs)
    blocks = load_blocks(bg)
    county, land, special_geom = build_land(bg)
    pantries = load_pantries(county)
    pantries["GEOID"] = site_geoids(pantries, bg)
    unmapped = pantries.loc[pantries["GEOID"].isna(), "j"].tolist()
    if unmapped:
        raise ValueError(f"Could not assign a block group to pantry IDs {unmapped}")
    m = len(pantries)

    # blockgroups.geojson
    keep = ["GEOID", "name", "h_total", "h_pov100", "h_pov185", "moe_pov100", "moe_pov185",
            "x_i", "y_i", "center_source", "x_centroid", "y_centroid", "x_cenpop",
            "y_cenpop", "pop2020", "included", "center_inside_polygon",
            "center_dist_outside_m", "geometry"]
    bg[keep].to_crs(CRS_LL).to_file(OUT / "blockgroups.geojson", driver="GeoJSON")
    gpd.GeoDataFrame({"name": ["Suffolk County, MA (land)"]}, geometry=[land], crs=CRS_M) \
        .to_crs(CRS_LL).to_file(OUT / "county_land.geojson", driver="GeoJSON")
    write_outline(land, OUT / "county_land_outline.csv")
    write_bg_demand(bg)

    blocks.round({"x_i": 1, "y_i": 1, "share": 6, "h_total": 4, "h_pov100": 4,
                  "h_pov185": 4}).to_csv(OUT / "demand_blocks.csv", index=False)
    pantries.drop(columns="geometry").to_csv(OUT / "pantries.csv", index=False)
    inc = bg[bg["included"]]

    for delta in DELTAS:
        grid = make_grid(delta, land, bg, m=m, special_geom=special_geom)
        log(f"grid_{delta}_N", len(grid))
        log(f"grid_{delta}_no_geoid", int(grid["GEOID"].isna().sum()))
        log(f"grid_{delta}_special_area", int(grid["special_area"].sum()))
        grid[["j", "X", "Y", "lon", "lat", "GEOID", "special_area"]].round(
            {"X": 1, "Y": 1}).to_csv(OUT / f"grid_{delta}.csv", index=False)

        sites = pd.concat([pantries[["j", "X", "Y"]], grid[["j", "X", "Y"]]], ignore_index=True)
        dist = distances(inc["GEOID"], inc["x_i"], inc["y_i"], sites, args.dmax)
        dist.to_parquet(OUT / f"distances_{delta}.parquet", index=False)
        log(f"reach_{delta}", reachable_report(dist, inc["GEOID"]))

        dist_b = distances(blocks["i"], blocks["x_i"], blocks["y_i"], sites, args.dmax)
        dist_b.to_parquet(OUT / f"distances_blocks_{delta}.parquet", index=False)
        log(f"reach_blocks_{delta}", reachable_report(dist_b, blocks["i"]))

    write_readme(args.dmax)
    write_checks_log()
    print(f"\nWrote outputs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
