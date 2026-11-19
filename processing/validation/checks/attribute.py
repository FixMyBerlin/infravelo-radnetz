# -*- coding: utf-8 -*-
"""
Attributprüfungen für B (Radverkehrsanlagen) und C (aggregiertes Netz).

Übernommen aus validate_datensatz_b.py und validate_datensatz_c.py:
fehlende Attribute, NULL-Werte, TODO-Werte, NULL bei „Keine Radinfrastruktur
vorhanden“, UNKNOWN in element_nr.
"""

import pandas as pd

from ..framework import Ergebnis, pruefung, verstoesse, zusammenfuegen

# Pflichtattribute je Datensatz (auf Vorhandensein, NULL und TODO geprüft)
PFLICHTATTRIBUTE = {
    "B": ["fuehr", "verkehrsri", "protek", "trennstreifen", "nutz_beschr", "farbe", "breite",
          "pflicht", "strassenname", "Bezirksnummer", "Länge", "beginnt_bei_vp", "endet_bei_vp"],
    "C": ["afid", "element_nr", "beginnt_bei_vp", "endet_bei_vp", "Länge", "ri", "verkehrsri",
          "Bezirksnummer", "strassenname", "fuehr", "pflicht", "breite", "ofm", "farbe", "protek",
          "trennstreifen", "nutz_beschr"],
}

KEINE_RADINFRA = "Keine Radinfrastruktur vorhanden"
MISCHVERKEHR = "Mischverkehr mit motorisiertem Verkehr"

# Bei „Keine Radinfrastruktur vorhanden“ müssen diese Attribute leer sein
LEER_BEI_KEINE_RADINFRA = ["verkehrsri", "protek", "trennstreifen", "nutz_beschr", "farbe", "breite", "pflicht"]


def _mit_radinfra(gdf):
    """Kanten mit Radinfrastruktur; bei „Keine Radinfrastruktur vorhanden“ sind NULL-Werte erwartet."""
    return gdf[gdf["fuehr"] != KEINE_RADINFRA] if "fuehr" in gdf else gdf


@pruefung("ATTRIBUTE", "Pflichtattribute vorhanden", datensaetze=["B", "C"],
          regel="Alle Pflichtattribute existieren als Spalte.")
def attribute_vorhanden(ctx, ds):
    gdf = ctx.datensatz(ds)
    fehlend = [a for a in PFLICHTATTRIBUTE[ds] if a not in gdf.columns]
    df = pd.DataFrame({"objekt": [f"Spalte {a}" for a in fehlend], "detail": "fehlt"})
    return Ergebnis(geprueft=len(PFLICHTATTRIBUTE[ds]), verstoesse=df)


@pruefung("NULL", "Keine NULL-Werte in Pflichtattributen", datensaetze=["B", "C"],
          regel="Pflichtattribute sind gefüllt. Ausnahmen: Kanten ohne Radinfrastruktur; "
                "breite nur bei fuehr ≠ Mischverkehr. Detail = Attribut.")
def null_werte(ctx, ds):
    gdf = _mit_radinfra(ctx.datensatz(ds))
    teile = []
    for attr in PFLICHTATTRIBUTE[ds]:
        if attr not in gdf:
            continue  # meldet ATTRIBUTE
        maske = gdf[attr].isna()
        if attr == "breite" and "fuehr" in gdf:
            maske &= gdf["fuehr"] != MISCHVERKEHR
        teile.append(verstoesse(gdf, maske, attr))
    return Ergebnis(geprueft=len(gdf), verstoesse=zusammenfuegen(teile))


@pruefung("TODO", "Keine TODO-Werte", datensaetze=["B", "C"],
          regel="Kein Pflichtattribut enthält „TODO“ (Groß-/Kleinschreibung egal), "
                "außer bei Kanten ohne Radinfrastruktur. Detail = Attribut.")
def todo_werte(ctx, ds):
    gdf = _mit_radinfra(ctx.datensatz(ds))
    teile = []
    for attr in PFLICHTATTRIBUTE[ds]:
        if attr not in gdf or pd.api.types.is_numeric_dtype(gdf[attr]):
            continue
        maske = gdf[attr].astype(str).str.contains("TODO", case=False, na=False) & gdf[attr].notna()
        teile.append(verstoesse(gdf, maske, attr))
    return Ergebnis(geprueft=len(gdf), verstoesse=zusammenfuegen(teile))


@pruefung("KEINE-RADINFRA-LEER", "„Keine Radinfrastruktur“ ohne Ausstattungswerte", datensaetze=["B", "C"],
          regel=f"Bei fuehr = „{KEINE_RADINFRA}“ sind {', '.join(LEER_BEI_KEINE_RADINFRA)} NULL. "
                "Detail = Attribut mit Wert.")
def keine_radinfra_leer(ctx, ds):
    gdf = ctx.datensatz(ds)
    gdf = gdf[gdf["fuehr"] == KEINE_RADINFRA]
    teile = [verstoesse(gdf, gdf[attr].notna(), attr) for attr in LEER_BEI_KEINE_RADINFRA if attr in gdf]
    return Ergebnis(geprueft=len(gdf), verstoesse=zusammenfuegen(teile))


@pruefung("ELEMENT-NR", "element_nr ohne UNKNOWN", datensaetze=["B", "C"],
          regel="element_nr enthält nicht „UNKNOWN“, jede Kante ist einer Netzkante zugeordnet.")
def element_nr_unknown(ctx, ds):
    gdf = ctx.datensatz(ds)
    maske = gdf["element_nr"].astype(str).str.contains("UNKNOWN", case=False, na=False)
    return Ergebnis(geprueft=len(gdf), verstoesse=verstoesse(gdf, maske, "element_nr"))
