#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_verteilung_ren.py
--------------------------------------------------------------------
Verteilung der Radverkehrsführungsformen auf dem REN+ ohne Radvorrangnetz.

Das HMM-Map-Matching (processing/map-matching) läuft dafür nicht auf dem RVN, sondern auf den
Kanten des REN+ (ren-network/output/ren_netz_gesamt.gpkg). Welche Kanten zählen, wählt `--netz`:
- `kartierung` (Standard): Kartierungs-Netz, also ohne die 2025 gelieferten Kanten
  (`bearbeitet_2025` ≠ ja)
- `ohne-vorrangnetz`: alle Kanten mit `radverkehrsnetz` ≠ Radvorrangnetz

Danach werden die Teilsegmente je Seite (ri=0 und ri=1) aufsummiert:
- je Führungsform nach infraVelo-Standard (`fuehr`)
- je TILDA-Wegeart (`tilda_category`; Fahrbahnen und Wege ohne Radinfrastruktur haben dort
  keinen Wert, dann gilt die Kategorie aus dem Routing-Netz, z. B. `mixedTrafficMotor`)

Bezugsgröße ist die Seitenlänge: jede Kante zählt zweimal (ri=0 und ri=1), also 2 × Achslänge.
Seiten, die die Einbahn-Regel des Matchings streicht, stehen in der Zeile
„Gegenrichtung entfällt (Einbahnstraße)“. So ergeben die Zeilen zusammen 100 %.

Kanten ohne `element_nr` bekommen für das Matching die Ersatz-ID `lfd_<lfd_nr>`.

Voraussetzung: TILDA-Routing ohne RVN-Zuschnitt (Rohdaten aus demselben Lauf wie das Routing):
    ../.venv/bin/python scripts/prepare_tilda_routing.py --ohne-rvn-zuschnitt \
        --output-dir output/ren-verteilung/TILDA-routing

INPUT (relativ zu processing/):
- ../ren-network/output/ren_netz_gesamt.gpkg
- output/ren-verteilung/TILDA-routing/TILDA Routing {Bikelanes,Streets,Paths} Translated.fgb

OUTPUT (output/ren-verteilung/):
- netz_<netz>.fgb                      (Eingangsnetz des Matchings)
- network_enriched_hmm.fgb             (Ergebnis des Matchings, für QGIS)
- verteilung_fuehrungsform.csv
- verteilung_tilda_wegeart.csv

Aufruf (aus processing/):
    ../.venv/bin/python validation/analyse_verteilung_ren.py
    ../.venv/bin/python validation/analyse_verteilung_ren.py --netz ohne-vorrangnetz
    ../.venv/bin/python validation/analyse_verteilung_ren.py --nur-auswertung
"""

import argparse
import logging
import subprocess
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

PROCESSING = Path(__file__).resolve().parents[1]
REN = PROCESSING.parent / "ren-network/output/ren_netz_gesamt.gpkg"
OUT_DIR = "output/ren-verteilung"
TILDA_DIR = f"{OUT_DIR}/TILDA-routing"
TILDA_SOURCES = ["bikelanes", "streets", "paths"]
NETZE = {
    "kartierung": ("Kartierungs-Netz (REN+ ohne die 2025 gelieferten Kanten)", lambda g: g["bearbeitet_2025"] != "ja"),
    "ohne-vorrangnetz": ("REN+ ohne Kanten des Radvorrangnetzes", lambda g: g["radverkehrsnetz"] != "Radvorrangnetz"),
}
ENTFAELLT = "Gegenrichtung entfällt (Einbahnstraße)"
OHNE_ZUORDNUNG = "(keine TILDA-Zuordnung)"


def tilda_path(source: str) -> Path:
    return PROCESSING / TILDA_DIR / f"TILDA Routing {source.title()} Translated.fgb"


def write_network(netz: str) -> Path:
    """Schreibt die ausgewählten REN+-Kanten als Eingangsnetz für das Matching."""
    ren = gpd.read_file(REN, layer="ren_netz")
    ren = ren[NETZE[netz][1](ren)].copy()
    ren["element_nr"] = ren["element_nr"].fillna("lfd_" + ren["lfd_nr"].astype(str))
    path = PROCESSING / OUT_DIR / f"netz_{netz}.fgb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    ren[["element_nr", "lfd_nr", "strassenname", "radverkehrsnetz", "bearbeitet_2025", "geometry"]].to_file(path, driver="FlatGeobuf")
    logging.info(f"Netz '{netz}': {len(ren)} Kanten, {ren.length.sum() / 1000:,.1f} km -> {path}")
    return path


def run_matching(network: Path):
    """Rust-Matching mit dem REN+-Netz und eigenem Ausgabeordner."""
    missing = [str(tilda_path(s)) for s in TILDA_SOURCES if not tilda_path(s).exists()]
    if missing:
        raise SystemExit("TILDA-Routing ohne RVN-Zuschnitt fehlt (siehe Docstring):\n  " + "\n  ".join(missing))
    tilda = ", ".join(f'{{data_source = "{s}", path = "{tilda_path(s).relative_to(PROCESSING)}"}}' for s in TILDA_SOURCES)
    cmd = [
        "cargo", "run", "--release", "-q", "--",
        "--set", f'paths.network="{network.relative_to(PROCESSING)}"',
        "--set", f'paths.output_dir="{OUT_DIR}"',
        "--set", f"paths.tilda=[{tilda}]",
        "run",
    ]
    logging.info("Starte Map-Matching auf dem REN+ …")
    subprocess.run(cmd, cwd=PROCESSING / "map-matching", check=True)


def wegeart(segments: gpd.GeoDataFrame) -> pd.Series:
    """TILDA-Wegeart je Teilsegment: tilda_category, sonst routing_category des Wegs."""
    routing_cat = pd.concat(
        pyogrio.read_dataframe(tilda_path(s), columns=["tilda_id", "routing_category"], read_geometry=False) for s in TILDA_SOURCES
    ).dropna().drop_duplicates("tilda_id").set_index("tilda_id")["routing_category"]
    return segments["tilda_category"].fillna(segments["tilda_id"].map(routing_cat)).fillna(OHNE_ZUORDNUNG)


def verteilung(segments: gpd.GeoDataFrame, key: str, achse_km: float) -> pd.DataFrame:
    """km und Anteil je Wert von `key`, getrennt nach ri und gesamt."""
    km = segments.pivot_table(index=key, columns="ri", values="km", aggfunc="sum", fill_value=0.0)
    km = km.reindex(columns=[0, 1], fill_value=0.0)
    # Was je Seite nicht als Teilsegment vorkommt, hat die Einbahn-Regel gestrichen.
    km.loc[ENTFAELLT] = [max(achse_km - km[ri].sum(), 0.0) for ri in (0, 1)]
    df = pd.DataFrame({
        "km_ri0": km[0],
        "anteil_ri0_prozent": km[0] / achse_km * 100,
        "km_ri1": km[1],
        "anteil_ri1_prozent": km[1] / achse_km * 100,
        "km_gesamt": km[0] + km[1],
        "anteil_gesamt_prozent": (km[0] + km[1]) / (2 * achse_km) * 100,
    })
    df = df[df["km_gesamt"] > 0].sort_values("km_gesamt", ascending=False)
    df.loc["Summe"] = df.sum()
    df.index.name = key
    return df.round(2)


def main():
    parser = argparse.ArgumentParser(description="Verteilung der Führungsformen auf dem REN+ ohne RVN (HMM-Map-Matching)")
    parser.add_argument("--netz", choices=NETZE, default="kartierung", help="Abgrenzung des Netzes (Standard: kartierung)")
    parser.add_argument("--nur-auswertung", action="store_true", help="Matching nicht neu rechnen, vorhandenes Ergebnis auswerten")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = PROCESSING / OUT_DIR

    network = out_dir / f"netz_{args.netz}.fgb"
    if not args.nur_auswertung:
        network = write_network(args.netz)
        run_matching(network)

    achse_km = pyogrio.read_dataframe(network, columns=[]).length.sum() / 1000
    segments = pyogrio.read_dataframe(out_dir / "network_enriched_hmm.fgb")
    segments["km"] = segments.length / 1000
    segments["tilda_wegeart"] = wegeart(segments)

    fuehr = verteilung(segments, "fuehr", achse_km)
    kategorie = verteilung(segments, "tilda_wegeart", achse_km)
    fuehr.to_csv(out_dir / "verteilung_fuehrungsform.csv")
    kategorie.to_csv(out_dir / "verteilung_tilda_wegeart.csv")

    logging.info(f"{NETZE[args.netz][0]}: {achse_km:,.1f} km Achslänge, {2 * achse_km:,.1f} km Seitenlänge")
    with pd.option_context("display.max_rows", None, "display.max_columns", None, "display.width", 250, "display.max_colwidth", 70):
        print(fuehr, kategorie, sep="\n\n")
    logging.info(f"✔ {out_dir}/verteilung_fuehrungsform.csv, verteilung_tilda_wegeart.csv")


if __name__ == "__main__":
    main()
