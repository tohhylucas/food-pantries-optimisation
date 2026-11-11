"""Turn the raw GBFB Partner Agency Locator listing into pantries_input.csv.

Source: https://www.gbfb.org/need-food/ (Vivery/AccessFood widget, GBFB network only),
search "02119", radius 10 miles, 173 results, retrieved 2026-11-11 and saved verbatim
to data/raw/pantries/gbfb_locator_raw.tsv. A 10-mile radius from Roxbury covers all
of Suffolk County (Winthrop ~6 mi, Revere ~7 mi, Hyde Park ~5 mi).

Steps:
  1. keep rows whose city is a Suffolk County municipality (Boston and its
     neighbourhood place names, Chelsea, Revere, Winthrop);
  2. strip in-building location notes from the street so the geocoder can match;
  3. merge listings that share a street address into one site (co-located
     programmes are one physical location for the model).

Run from the project root:
    .venv/Scripts/python.exe -I src/prepare_pantries.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "pantries" / "gbfb_locator_raw.tsv"
OUT = ROOT / "data" / "raw" / "pantries" / "pantries_input.csv"

SUFFOLK_PLACES = {
    "Boston", "Roxbury", "Dorchester", "Jamaica Plain", "South Boston", "East Boston",
    "Charlestown", "Allston", "Brighton", "Roslindale", "Mattapan", "Hyde Park",
    "West Roxbury", "Chelsea", "Revere", "Winthrop",
}

# Location notes in the listing that are not part of the street address.
STREET_FIXES = {
    "889 Harrison Ave at the outside window": "889 Harrison Ave",
    "850 Harrison Ave Yawkey Building Basement": "850 Harrison Ave",
    "450 Brookline Avenue Smith 101": "450 Brookline Avenue",
    "100 William T Morrissey Blvd Campus Center Suite 2300": "100 William T Morrissey Blvd",
    "525 River St. Mattapan": "525 River St.",
    "Central Square Park 197 Border St": "197 Border St",
    "640 Washington St #202-201": "640 Washington St",
    "738 Broadway St Unit B": "738 Broadway St",
    "First Congregational Church of Revere 230 Beach Street": "230 Beach Street",
}

ABBREV = [(r"\bstreet\b", "st"), (r"\bavenue\b", "ave"), (r"\bhighway\b", "hwy"),
          (r"\broad\b", "rd"), (r"\bboulevard\b", "blvd"), (r"\bdrive\b", "dr")]


def norm_street(s: str) -> str:
    s = re.sub(r"[.,]", "", s.lower()).strip()
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s)


def main() -> None:
    raw = pd.read_csv(RAW, sep="\t", dtype=str)
    raw["city"] = raw["city"].str.strip()
    print(f"raw GBFB rows: {len(raw)}")

    suf = raw[raw["city"].isin(SUFFOLK_PLACES)].copy()
    print(f"rows with a Suffolk County place name: {len(suf)}")
    print("  by place:", suf["city"].value_counts().to_dict())

    suf["address"] = suf["street"].replace(STREET_FIXES)
    suf["key"] = suf["address"].map(norm_street) + "|" + suf["zip"]

    merged = (suf.groupby("key", sort=False)
              .agg(name=("name", lambda s: " ; ".join(dict.fromkeys(s))),
                   address=("address", "first"), city=("city", "first"),
                   state=("state", "first"), zip=("zip", "first"),
                   gbfb_idx=("idx", lambda s: ",".join(s)),
                   n_listings=("idx", "size"))
              .reset_index(drop=True))
    dup = merged[merged["n_listings"] > 1]
    print(f"distinct sites after merging shared addresses: {len(merged)}")
    for _, r in dup.iterrows():
        print(f"  merged [{r.gbfb_idx}] {r.address}: {r['name']}")

    merged["capacity"] = ""  # not published by GBFB; left blank on purpose
    merged["source"] = "GBFB Partner Agency Locator, retrieved 2026-11-11"
    cols = ["name", "address", "city", "state", "zip", "capacity", "gbfb_idx",
            "n_listings", "source"]
    merged[cols].to_csv(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
