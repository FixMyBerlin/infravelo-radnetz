#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_kreuzungswege_auf_strecke.py
--------------------------------------------------------------------
Findet Kreuzungswege in Datensatz B, die nicht an einem Knotenpunkt liegen,
sondern auf der Strecke, z. B. wenn ein Schutzstreifen vom Seitenraum auf die
Fahrbahn verschwenkt.

Logik:
1. Kreuzungswege aus Datensatz B: fuehr = „Kreuzungsweg“ (TILDA category=crossing)
   und „Kreuzungsweg (Konvertiert)“ (start_bikelane_conversion.py)
2. Abstand jedes Segments zum nächsten Knotenpunkt des Abgabestands, virtuelle eingeschlossen
3. Auf der Strecke: Abstand > --abstand (Standard 25 m, wie der Radius der Konvertierung)
4. Kennzeichnung, ob das Segment eine andere benannte Straße quert, die nicht im Netz ist
   (TILDA-Straße mit anderem Namen innerhalb von 10 m). Dann ist es eher die Einmündung
   einer Nebenstraße als eine Verschwenkung oder Querung auf der Strecke.

INPUT:
- output/snapping_converted_bikelanes{_ren}{_clip}.fgb (Datensatz B)
- ../knotenpunkte/output/knotenpunkte_abgabe.gpkg
- output/TILDA-routing{-ren}/TILDA Routing Streets Translated.fgb

OUTPUT:
- output/analysis/kreuzungswege_auf_strecke{_ren}{_clip}.fgb, zum Ansehen in QGIS
- Übersicht im Terminal

Aufruf aus processing/:
    ../.venv/bin/python analysis/analyse_kreuzungswege_auf_strecke.py [--netz ren|rvn] [--clip ...] [--abstand 25]
"""

import geopandas as gpd
import pandas as pd

from pfade import Pfade, argumente

KREUZUNGSWEGE = ["Kreuzungsweg", "Kreuzungsweg (Konvertiert)"]
KP_ID = "Knotenpunkt‐ID"  # mit U+2010 wie im Abgabestand
STRASSE_PUFFER_M = 10.0

SPALTEN = ["sfid", "element_nr", "ri", "Bezirksnummer", "strassenname", "fuehr", "Länge",
           "tilda_id", "tilda_name", "tilda_category", "edge_source"]


def gequerte_strassen(kw: gpd.GeoDataFrame, strassen: gpd.GeoDataFrame) -> pd.Series:
    """Je Kreuzungsweg die Namen der TILDA-Straßen in der Nähe, deren Name von der Netzkante abweicht."""
    puffer = kw[["strassenname", "geometry"]].copy()
    puffer["geometry"] = kw.buffer(STRASSE_PUFFER_M)
    treffer = gpd.sjoin(puffer, strassen[["tilda_name", "geometry"]], predicate="intersects")
    treffer = treffer[treffer["tilda_name"].notna() & (treffer["tilda_name"] != treffer["strassenname"].fillna(""))]
    namen = treffer.groupby(level=0)["tilda_name"].agg(lambda s: ", ".join(sorted(set(s))))
    return namen.reindex(kw.index)


def main():
    parser = argumente("Kreuzungswege auf der Strecke, nicht an einem Knotenpunkt")
    parser.add_argument("--abstand", type=float, default=25.0,
                        help="Mindestabstand zum nächsten Knotenpunkt in m (Standard: 25, wie die Konvertierung)")
    args = parser.parse_args()
    p = Pfade(args.netz, args.clip)

    for pfad in (p.datensatz_b, p.knotenpunkte_abgabe, p.tilda_routing("streets")):
        if not pfad.exists():
            raise SystemExit(f"❌ Datei fehlt: {pfad}")

    b = gpd.read_file(p.datensatz_b)
    kw = b[b["fuehr"].isin(KREUZUNGSWEGE)][[c for c in SPALTEN if c in b] + ["geometry"]].copy()
    kp = gpd.read_file(p.knotenpunkte_abgabe, columns=[KP_ID, "ist_virtuell", "KP_Nichtbetrachten"]).to_crs(kw.crs)

    naechster = gpd.sjoin_nearest(kw[["geometry"]], kp, distance_col="abstand_kp_m")
    naechster = naechster[~naechster.index.duplicated()]  # gleich weit entfernte Knotenpunkte
    kw["abstand_kp_m"] = naechster["abstand_kp_m"].round(1)
    kw["naechster_kp"] = naechster[KP_ID]
    kw["kp_virtuell"] = naechster["ist_virtuell"].fillna(0).astype(int)

    strecke = kw[kw["abstand_kp_m"] > args.abstand].copy()
    strassen = gpd.read_file(p.tilda_routing("streets"), columns=["tilda_name"]).to_crs(kw.crs)
    strecke["gequerte_strasse"] = gequerte_strassen(strecke, strassen)
    strecke["quert_nebenstrasse"] = strecke["gequerte_strasse"].notna()
    strecke = strecke.sort_values("abstand_kp_m", ascending=False)

    ausgabe = p.analyse("kreuzungswege_auf_strecke.fgb")
    strecke.to_file(ausgabe, driver="FlatGeobuf")

    print("=" * 80)
    print(f"KREUZUNGSWEGE AUF DER STRECKE ({p.datensatz_b.name}, > {args.abstand:g} m zum nächsten Knotenpunkt)")
    print("=" * 80)
    tabelle = pd.DataFrame({
        "gesamt": kw.groupby("fuehr").size(),
        "auf Strecke": strecke.groupby("fuehr").size(),
        "davon Nebenstraße": strecke[strecke["quert_nebenstrasse"]].groupby("fuehr").size(),
    }).fillna(0).astype(int)
    tabelle.loc["Summe"] = tabelle.sum()
    print(tabelle.to_string())

    ohne = strecke[~strecke["quert_nebenstrasse"]]
    print(f"\nOhne gequerte Nebenstraße, die 15 am weitesten entfernten (von {len(ohne)}):")
    print(ohne[["fuehr", "strassenname", "tilda_id", "Länge", "abstand_kp_m"]].head(15).to_string(index=False))
    print(f"\n✔ {len(strecke)} Segmente -> {ausgabe}")


if __name__ == "__main__":
    main()
