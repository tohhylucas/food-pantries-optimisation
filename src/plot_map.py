"""Maps for the Suffolk County, MA food-pantry model (handover TODO 8 + overview map).

Run from the project root after src/build_data.py:
    .venv/Scripts/python.exe -I src/plot_map.py                 # static PNGs
    .venv/Scripts/python.exe -I src/plot_map.py --delta 750     # any spacing
    .venv/Scripts/python.exe -I src/plot_map.py --interactive   # slider window

Outputs (data/processed/):
    qa_map.png               TODO 8 QA map at delta = 500 m
    poverty_map_{delta}.png  red = people below poverty per block group,
                             green = existing pantries, grey = candidate grid
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import CRS_M, OUT, make_grid  # noqa: E402

RED = "#d62728"
RED_EDGE = "#8b0000"
GREEN = "#1a9850"
GRID_GREY = "#7f7f7f"
WATER = "#dce9f2"
LAND = "#fbfbf8"
BG_LINE = "#9a9a9a"
INK = "#222222"

# Marker area (pt^2) per person below poverty, and per unit of pantry capacity.
POV_AREA_PER_PERSON = 0.35
PANTRY_AREA_PER_PERSON = 0.15
PANTRY_DEFAULT_AREA = 60  # used when capacity is unknown


def load():
    bg = gpd.read_file(OUT / "blockgroups.geojson").to_crs(CRS_M)
    land = gpd.read_file(OUT / "county_land.geojson").to_crs(CRS_M).geometry.iloc[0]
    pantries = pd.read_csv(OUT / "pantries.csv")
    special = bg[bg["GEOID"].str[5:7] == "98"].geometry.union_all()
    bg_land = bg.copy()
    bg_land["geometry"] = bg.geometry.intersection(land)  # draw boundaries on land only
    return bg, bg_land, land, pantries, special


def _base(ax, bg_land, land):
    ax.set_facecolor(WATER)
    gpd.GeoSeries([land], crs=CRS_M).plot(ax=ax, color=LAND, linewidth=0)
    bg_land.boundary.plot(ax=ax, color=BG_LINE, linewidth=0.35)
    gpd.GeoSeries([land], crs=CRS_M).boundary.plot(ax=ax, color=INK, linewidth=0.8)
    minx, miny, maxx, maxy = land.bounds
    pad = 800
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _scalebar(ax, land, length=2000):
    minx, miny, _, _ = land.bounds
    x0, y0 = minx + 300, miny + 300
    ax.plot([x0, x0 + length], [y0, y0], color=INK, linewidth=2, solid_capstyle="butt")
    ax.text(x0 + length / 2, y0 + 180, f"{length / 1000:g} km", ha="center",
            va="bottom", fontsize=8, color=INK)


def _pantry_sizes(p):
    cap = pd.to_numeric(p.get("capacity"), errors="coerce")
    return np.where(cap.notna(), cap * PANTRY_AREA_PER_PERSON, PANTRY_DEFAULT_AREA)


def draw_poverty_map(ax, bg, bg_land, land, pantries, grid, delta):
    """Red circle per block group (area ∝ h_pov100), green pantries, grey grid."""
    ax.clear()
    _base(ax, bg_land, land)

    ax.scatter(grid["X"], grid["Y"], s=2 if delta < 400 else 5, color=GRID_GREY,
               alpha=0.55, linewidths=0, zorder=2)

    inc = bg[bg["included"] & (bg["h_pov100"] > 0)].sort_values("h_pov100", ascending=False)
    ax.scatter(inc["x_i"], inc["y_i"], s=inc["h_pov100"] * POV_AREA_PER_PERSON,
               facecolor=RED, edgecolor=RED_EDGE, alpha=0.45, linewidths=0.4, zorder=3)

    if len(pantries):
        ax.scatter(pantries["X"], pantries["Y"], s=_pantry_sizes(pantries), color=GREEN,
                   edgecolor="white", linewidths=0.8, zorder=4)

    # Legend: size key for red circles + identity for the other layers.
    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=np.sqrt(v * POV_AREA_PER_PERSON),
               markerfacecolor=RED, markeredgecolor=RED_EDGE, alpha=0.6,
               label=f"{v:,} people below poverty")
        for v in (100, 500, 1000)
    ]
    no_cap = len(pantries) and pd.to_numeric(pantries["capacity"], errors="coerce").isna().all()
    pantry_label = (f"Existing pantry (m = {len(pantries)})"
                    + (" — capacity unknown, uniform size" if no_cap else ", area ∝ capacity")
                    if len(pantries) else "Existing pantries: none loaded yet (placeholder)")
    handles += [
        Line2D([], [], marker="o", linestyle="", markersize=7, markerfacecolor=GREEN,
               markeredgecolor="white", label=pantry_label),
        Line2D([], [], marker="o", linestyle="", markersize=3, markerfacecolor=GRID_GREY,
               markeredgecolor="none", label=f"Candidate site, Δ = {delta:g} m (N = {len(grid):,})"),
        Line2D([], [], color=BG_LINE, linewidth=1, label="Block-group boundary"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8, frameon=True, framealpha=0.92,
              labelspacing=1.1, borderpad=0.9, edgecolor="#cccccc")
    _scalebar(ax, land)
    ax.set_title(
        f"Suffolk County, MA — people below the poverty line (ACS 2020–24, C17002) "
        f"and candidate pantry grid\n"
        f"{int(inc['h_pov100'].sum()):,} people below 1.00× poverty across "
        f"{int(bg['included'].sum())} populated block groups",
        fontsize=10, color=INK, loc="left")


def draw_qa_map(ax, fig, bg, bg_land, land, pantries, grid, delta):
    """TODO 8: shading by h_pov100, centres, grid, pantries, outline."""
    _base(ax, bg_land, land)
    shaded = bg_land[bg_land["included"]]
    shaded.plot(ax=ax, column="h_pov100", cmap="Oranges", linewidth=0.3,
                edgecolor="white", zorder=1, legend=True,
                legend_kwds={"label": "People below 1.00× poverty (h_pov100)",
                             "shrink": 0.55, "pad": 0.01})
    bg_land[~bg_land["included"]].plot(ax=ax, color="#e6e6e6", hatch="///",
                                       edgecolor="#bbbbbb", linewidth=0.3, zorder=1)
    gpd.GeoSeries([land], crs=CRS_M).boundary.plot(ax=ax, color=INK, linewidth=0.9, zorder=2)
    ax.scatter(grid["X"], grid["Y"], s=4, color="#4a6fa5", alpha=0.45, linewidths=0, zorder=3)
    ax.scatter(bg["x_i"], bg["y_i"], s=4, color=INK, linewidths=0, zorder=4)
    bad = bg[~bg["center_inside_polygon"]]
    ax.scatter(bad["x_i"], bad["y_i"], s=40, facecolor="none", edgecolor="#c51b8a",
               linewidths=1.0, zorder=5)
    if len(pantries):
        ax.scatter(pantries["X"], pantries["Y"], marker="^", s=55, color=GREEN,
                   edgecolor="white", linewidths=0.8, zorder=6)
    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=3, color=INK,
               label="Block-group centre (x_i, y_i)"),
        Line2D([], [], marker="o", linestyle="", markersize=7, markerfacecolor="none",
               markeredgecolor="#c51b8a", label=f"Centre outside its polygon ({len(bad)})"),
        Line2D([], [], marker="o", linestyle="", markersize=3, color="#4a6fa5", alpha=0.6,
               label=f"Candidate grid, Δ = {delta:g} m (N = {len(grid):,})"),
        Line2D([], [], marker="^", linestyle="", markersize=7, color=GREEN,
               label=f"Existing pantry (m = {len(pantries)})" if len(pantries)
               else "Existing pantries: none loaded (placeholder)"),
        Line2D([], [], color=INK, linewidth=1, label="County land outline (water removed)"),
        plt.Rectangle((0, 0), 1, 1, facecolor="#e6e6e6", edgecolor="#bbbbbb", hatch="///",
                      label="Excluded from I (h_total = 0)"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.92,
              edgecolor="#cccccc")
    _scalebar(ax, land)
    ax.set_title(f"QA map — Suffolk County, MA block groups, EPSG:26986, Δ = {delta:g} m",
                 fontsize=10, color=INK, loc="left")


def static(deltas):
    bg, bg_land, land, pantries, special = load()
    m = len(pantries)
    for delta in deltas:
        grid = make_grid(delta, land, bg, m=m, special_geom=special)
        fig, ax = plt.subplots(figsize=(10, 11), dpi=170)
        draw_poverty_map(ax, bg, bg_land, land, pantries, grid, delta)
        fig.tight_layout()
        fig.savefig(OUT / f"poverty_map_{delta:g}.png", facecolor="white")
        plt.close(fig)
        print(f"wrote poverty_map_{delta:g}.png  (N = {len(grid)})")

    grid = make_grid(500, land, bg, m=m, special_geom=special)
    fig, ax = plt.subplots(figsize=(11, 11), dpi=170)
    draw_qa_map(ax, fig, bg, bg_land, land, pantries, grid, 500)
    fig.tight_layout()
    fig.savefig(OUT / "qa_map.png", facecolor="white")
    plt.close(fig)
    print("wrote qa_map.png")


def interactive(start=500):
    from matplotlib.widgets import Slider

    bg, bg_land, land, pantries, special = load()
    m = len(pantries)
    fig, ax = plt.subplots(figsize=(10, 11))
    fig.subplots_adjust(bottom=0.08)
    sax = fig.add_axes([0.2, 0.025, 0.6, 0.025])
    slider = Slider(sax, "Grid Δ (m)", 150, 2000, valinit=start, valstep=50)

    def redraw(delta):
        grid = make_grid(delta, land, bg, m=m, special_geom=special)
        draw_poverty_map(ax, bg, bg_land, land, pantries, grid, delta)
        fig.canvas.draw_idle()

    slider.on_changed(redraw)
    redraw(start)
    plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", type=float, nargs="*", default=[1000, 500, 250])
    ap.add_argument("--interactive", action="store_true")
    a = ap.parse_args()
    if a.interactive:
        interactive(a.delta[0] if a.delta else 500)
    else:
        static(a.delta)
