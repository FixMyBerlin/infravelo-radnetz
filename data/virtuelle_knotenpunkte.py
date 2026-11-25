#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
virtuelle_knotenpunkte.py
--------------------------------------------------------------------
Virtual nodes (virtuelle Knotenpunkte). Rules: data/VIRTUELLE-KNOTENPUNKTE.md.

Sources:
- The 53 nodes of 2025 (0001-0053) are entries of the Netzanpassungen app (KV database, herkunft
  rvn_2025, id_rvn_2025 = the id in the 2025 delivery: V1112, V44530016-44530064, ...). The app took them
  over once from netzanpassungen/one_time_import/2025/Virtuelle-Knotenpunkte.gpkg (now an archive) when
  the area berlin was opened by a logged-in user. read_registry() reads them from the database; step 1
  splits REN+ at them, step 3 copies them into the output file.
- netzanpassungen/output/virtuelle_knoten.gpkg (OUTPUT_PATH): written by step 3
  (netzanpassungen/apply_app_result.py) = the 53 + every node of the Netzanpassungen app (active and
  deleted). This is what processing/ and knotenpunkte/ read through read_active().

Numbers are given only by the Netzanpassungen app (counter in its KV database). The commands of 2026-11
that gave numbers here (nummerieren, uebernehmen, loeschen, umnummerieren) are done and removed; see
data/VIRTUELLE-KNOTENPUNKTE.md.

As a module: read_active() gives the active virtual nodes for the pipeline, read_all() all rows of a
file, read_registry() the 53 of 2025, translate_element_nr() translates 2025 ids in an element_nr.

Call (in the repo root):
    .venv/bin/python data/virtuelle_knotenpunkte.py pruefen
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
# The 53 of 2025 as delivered; an archive since they live in the app (read only for tests and old ids)
ARCHIVE_PATH = ROOT / "netzanpassungen" / "one_time_import" / "2025" / "Virtuelle-Knotenpunkte.gpkg"
PATH = ARCHIVE_PATH
REGISTRY_PATH = ARCHIVE_PATH
HERKUNFT_2025 = "rvn_2025"
AREA_2025 = "berlin"
OUTPUT_PATH = ROOT / "netzanpassungen" / "output" / "virtuelle_knoten.gpkg"  # step 3: the 53 + app nodes
LAYER = "Virtuelle-Knotenpunkte"
OLD_TO_NEW_PATH = DATA_DIR / "virtuelle_knotenpunkte_alt_neu.csv"
CRS = "EPSG:25833"

ID_COLUMN = "Knotenpunkt-ID"  # with an ASCII hyphen, as in this file since 2025
ID_PATTERN = re.compile(r"^\d{4}$")
ID_DIGITS = 4
STATUS_ACTIVE = "aktiv"
STATUS_DELETED = "geloescht"
REGISTRY_SIZE = 53

# Columns of the registry; the output file of step 3 has the same plus OUTPUT_EXTRA_COLUMNS
COLUMNS = [ID_COLUMN, "ist_virtuell", "status", "angelegt_am", "geloescht_am", "grund",
           "id_rvn_2025", "quelle", "kommentar"]
OUTPUT_EXTRA_COLUMNS = ["herkunft", "app_eintrag", "vorschlag_id", "traeger_netz", "traeger_element_nr", "station_m"]
TEXT_COLUMNS = ["status", "angelegt_am", "geloescht_am", "grund", "id_rvn_2025", "quelle", "kommentar",
                "herkunft", "app_eintrag", "vorschlag_id", "traeger_netz", "traeger_element_nr"]

MISSING_OUTPUT_MESSAGE = (
    f"Virtual nodes missing: {OUTPUT_PATH} does not exist. Run step 3 first "
    "(netzanpassungen/apply_app_result.py, or ./run_pipeline.sh); it writes the 53 nodes of 2025 together "
    "with the nodes of the Netzanpassungen app.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _text(value):
    """Ids and texts always as str; empty values as None. 12.0 -> '12' (pad_id adds the leading zeros)."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def pad_id(value):
    """'12' -> '0012'. Other values stay as they are and show up in check()."""
    text = _text(value)
    if text is not None and text.isdigit() and len(text) < ID_DIGITS:
        return text.zfill(ID_DIGITS)
    return text


def read_all(path=OUTPUT_PATH):
    """All rows of a file of virtual nodes (deleted ones included), in EPSG:25833. Default: output of step 3."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(MISSING_OUTPUT_MESSAGE if path == OUTPUT_PATH else f"Missing: {path}")
    gdf = gpd.read_file(path, layer=LAYER)
    if gdf.crs is None or gdf.crs.to_string() != CRS:
        gdf = gdf.to_crs(CRS)
    for column in COLUMNS:
        if column not in gdf.columns:
            gdf[column] = None
    gdf[ID_COLUMN] = gdf[ID_COLUMN].map(pad_id)
    for column in TEXT_COLUMNS:
        if column in gdf.columns:
            gdf[column] = gdf[column].map(_text)
    return gdf


def registry_from_entries(entries):
    """The nodes of 2025 among the app entries (virtual_node with herkunft rvn_2025), as registry rows."""
    from pyproj import Transformer
    from shapely.geometry import Point

    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    rows = []
    for entry in entries:
        data = entry.get("data") or {}
        if data.get("kind") != "virtual_node" or data.get("herkunft") != HERKUNFT_2025:
            continue
        deleted = bool(data.get("geloescht"))
        rows.append({
            ID_COLUMN: pad_id(data.get("nummer")), "ist_virtuell": 1,
            "status": STATUS_DELETED if deleted else STATUS_ACTIVE,
            "angelegt_am": "2025",
            "geloescht_am": (data.get("geloescht_am") or entry.get("updated_at")) if deleted else None,
            "grund": (data.get("grund") or "in der App gelöscht") if deleted else None,
            "id_rvn_2025": data.get("id_rvn_2025"), "quelle": "RVN 2025", "kommentar": data.get("kommentar"),
            "app_eintrag": entry.get("id"),
            "geometry": Point(*to_utm.transform(*data["lngLat"])),
        })
    gdf = gpd.GeoDataFrame(rows, columns=COLUMNS + ["app_eintrag", "geometry"], geometry="geometry", crs=CRS)
    return gdf.sort_values(ID_COLUMN).reset_index(drop=True)


def read_registry(path=None, entries=None):
    """The 53 nodes of 2025. Default: from the app entries in the KV database (`entries`, else fetched for
    area berlin); `path`: from a file (the archive, tests). Stops when they are not all there or break the rules.
    Deleted ones stay in the result with status geloescht (their number stays taken)."""
    if path is None:
        if entries is None:
            sys.path.insert(0, str(ROOT / "netzanpassungen"))
            import kv_entries
            entries = kv_entries.fetch_entries(AREA_2025)["entries"]
        gdf = registry_from_entries(entries)
        missing = sorted({str(n).zfill(ID_DIGITS) for n in range(1, REGISTRY_SIZE + 1)} - set(gdf[ID_COLUMN]))
        if missing:
            raise SystemExit(
                f"{len(missing)} of the {REGISTRY_SIZE} nodes of 2025 are not in the Netzanpassungen app yet "
                f"(e.g. {missing[:3]}). Open the area {AREA_2025} once in the app while logged in: it takes them "
                "over from netzanpassungen/one_time_import/2025/ by itself.")
        errors = check(gdf)
        if errors:
            raise ValueError("The nodes of 2025 in the app break the rules:\n- " + "\n- ".join(errors))
        return gdf
    gdf = read_all(path)
    errors = check(gdf)
    if errors:
        raise ValueError(f"{Path(path).name} breaks the rules (data/VIRTUELLE-KNOTENPUNKTE.md):\n- " + "\n- ".join(errors))
    gdf["ist_virtuell"] = 1
    return gdf


def read_active(path=OUTPUT_PATH):
    """Active virtual nodes with their number, from the output of step 3 (the 53 + the app nodes).
    Stops with a clear message when the file is missing or breaks the rules."""
    gdf = read_all(path)
    errors = check(gdf)
    if errors:
        raise ValueError(f"{Path(path).name} breaks the rules (data/VIRTUELLE-KNOTENPUNKTE.md):\n- " + "\n- ".join(errors))
    active = gdf[gdf["status"] == STATUS_ACTIVE].reset_index(drop=True)
    active["ist_virtuell"] = 1
    logging.info(f"Virtual nodes ({Path(path).name}): {len(active)} active, {len(gdf) - len(active)} deleted")
    return active


def old_to_new(path=REGISTRY_PATH):
    """Id of the 2025 delivery (e.g. 'V44530016-44530064') -> number, for data from before 2026-11."""
    gdf = read_all(path)
    known = gdf[gdf["id_rvn_2025"].notna()]
    return dict(zip(known["id_rvn_2025"], known[ID_COLUMN]))


def translate_element_nr(element_nr, mapping=None):
    """Replace the 2025 ids in an element_nr by the numbers: 'V6475_V4789.01' -> '0039_0022.01'.
    Other element_nr stay unchanged."""
    if not isinstance(element_nr, str):
        return element_nr
    mapping = old_to_new() if mapping is None else mapping
    match = re.match(r"^(.+?)_(.+)(\.\d+)$", element_nr)
    if not match:
        return element_nr
    von, bis, suffix = match.groups()
    return f"{mapping.get(von, von)}_{mapping.get(bis, bis)}{suffix}"


def rule_violations(gdf):
    """Broken rules as a list of (rule, affected entries); empty when everything is fine.

    Basis of check() and of the validation (processing/validation/checks/virtuelle_knotenpunkte.py).
    """
    found = []
    numbered = gdf[gdf[ID_COLUMN].notna()]
    bad = numbered[~numbered[ID_COLUMN].str.match(ID_PATTERN)]
    if len(bad):
        found.append(("Number not four digits", sorted(bad[ID_COLUMN])))
    duplicated = numbered[ID_COLUMN][numbered[ID_COLUMN].duplicated()]
    if len(duplicated):
        found.append(("Number given twice (deleted ones count too)", sorted(set(duplicated))))
    unnumbered = gdf[gdf[ID_COLUMN].isna()]
    if len(unnumbered):
        found.append(("Point without number",
                      sorted(f"no number ({q or 'no quelle'})" for q in unnumbered["quelle"])))
    status = gdf[~gdf["status"].isin([STATUS_ACTIVE, STATUS_DELETED]) & gdf[ID_COLUMN].notna()]
    if len(status):
        found.append((f"status must be '{STATUS_ACTIVE}' or '{STATUS_DELETED}'", sorted(status[ID_COLUMN])))
    deleted = gdf[gdf["status"] == STATUS_DELETED]
    no_date = deleted[deleted["geloescht_am"].isna() | deleted["grund"].isna()]
    if len(no_date):
        found.append(("Deleted without geloescht_am or grund", sorted(no_date[ID_COLUMN])))
    old = gdf["id_rvn_2025"].dropna()
    if old.duplicated().any():
        found.append(("id_rvn_2025 twice", sorted(set(old[old.duplicated()]))))
    if "app_eintrag" in gdf.columns:
        app = gdf["app_eintrag"].dropna()
        if app.duplicated().any():
            found.append(("App entry twice", sorted(set(app[app.duplicated()]))))
    empty = gdf[gdf.geometry.isna() | gdf.geometry.is_empty]
    if len(empty):
        found.append(("Point without geometry", sorted(empty[ID_COLUMN].fillna("no number"))))
    return found


def check(gdf):
    """Rule violations as a list of sentences; empty when everything is fine."""
    errors = []
    for rule, entries in rule_violations(gdf):
        if rule == "Point without number":
            errors.append(f"{len(entries)} point(s) without number")
        else:
            errors.append(f"{rule}: {entries}")
    return errors


def check_registry_frozen(gdf):
    """The registry holds exactly the 53 active nodes 0001-0053, each with its id_rvn_2025."""
    errors = []
    expected = {str(number).zfill(ID_DIGITS) for number in range(1, REGISTRY_SIZE + 1)}
    if set(gdf[ID_COLUMN].dropna()) != expected or len(gdf) != REGISTRY_SIZE:
        errors.append(f"The registry must hold exactly 0001-{REGISTRY_SIZE:04d} ({len(gdf)} rows); "
                      "new nodes are set only in the Netzanpassungen app")
    if (gdf["status"] != STATUS_ACTIVE).any():
        errors.append(f"Registry rows not active: {sorted(gdf.loc[gdf['status'] != STATUS_ACTIVE, ID_COLUMN])}")
    if gdf["id_rvn_2025"].isna().any():
        errors.append(f"Registry rows without id_rvn_2025: {sorted(gdf.loc[gdf['id_rvn_2025'].isna(), ID_COLUMN])}")
    return errors


def highest_number(gdf):
    """Highest number ever given in a file (deleted numbers count)."""
    numbers = gdf[ID_COLUMN].dropna()
    numbers = numbers[numbers.str.match(ID_PATTERN)].astype(int)
    return int(numbers.max()) if len(numbers) else 0


def cmd_pruefen(_args):
    registry = read_all(REGISTRY_PATH)
    errors = [f"{REGISTRY_PATH.name}: {error}" for error in check(registry) + check_registry_frozen(registry)]
    logging.info(f"{REGISTRY_PATH.name}: {len(registry)} rows (frozen, 2025)")
    if OUTPUT_PATH.exists():
        output = read_all(OUTPUT_PATH)
        errors += [f"{OUTPUT_PATH.name}: {error}" for error in check(output)]
        active = (output["status"] == STATUS_ACTIVE).sum()
        logging.info(f"{OUTPUT_PATH.name}: {len(output)} rows, {active} active, highest number "
                     f"{str(highest_number(output)).zfill(ID_DIGITS)}")
    else:
        logging.warning(MISSING_OUTPUT_MESSAGE)
    for error in errors:
        logging.error(error)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description="Check the virtual nodes (registry of 2025 and output of step 3)")
    sub = parser.add_subparsers(dest="befehl", required=True)
    sub.add_parser("pruefen", help="check the rules").set_defaults(func=cmd_pruefen)
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
