# -*- coding: utf-8 -*-
"""
Prüfungen der Knotenpunkte (K).

Übernommen aus validate_knotenpunkte.py: Pflichtfelder bei zu betrachtenden Knotenpunkten.
Neu: kein Feld NULL (VALIDIERUNG_OFFEN.md, „Knotenpunkte ohne NULL“).
"""

import pandas as pd

from ..datasets import KP_ID
from ..framework import Ergebnis, pruefung, verstoesse, zusammenfuegen

# Pflichtfelder, wenn KP_Nichtbetrachten = 0
PFLICHTFELDER_BEI_BETRACHTUNG = [KP_ID, "Bezirksnummer", "KP_HVS", "LSA_KP", "Mar_RVF_KP",
                                 "Furt_rot", "Fl_Linksab", "vorgez_Fl", "RFS_Mitte"]


@pruefung("PFLICHTFELDER", "Pflichtfelder bei zu betrachtenden Knotenpunkten", datensaetze="K",
          regel="Bei KP_Nichtbetrachten = 0 sind alle Pflichtfelder gefüllt "
                f"({', '.join(PFLICHTFELDER_BEI_BETRACHTUNG)}). Detail = Feld.")
def pflichtfelder(ctx, ds):
    gdf = ctx.datensatz(ds)
    gdf = gdf[gdf["KP_Nichtbetrachten"] == 0]
    teile = []
    for feld in PFLICHTFELDER_BEI_BETRACHTUNG:
        if feld not in gdf:
            teile.append(pd.DataFrame({"objekt": [f"Spalte {feld}"], "detail": ["fehlt"]}))
            continue
        teile.append(verstoesse(gdf, gdf[feld].isna(), feld))
    return Ergebnis(geprueft=len(gdf), verstoesse=zusammenfuegen(teile))


@pruefung("NULL", "Kein Feld NULL", datensaetze="K",
          regel="Kein Attribut ist NULL oder leer. Ist nichts zu erfassen, steht dort „keins“. "
                "Geprüft werden alle Spalten der Abgabedatei. Detail = Feld.")
def keine_null_werte(ctx, ds):
    gdf = ctx.datensatz(ds)
    teile = []
    for feld in gdf.columns:
        if feld in ("_key", gdf.geometry.name):
            continue
        werte = gdf[feld]
        maske = werte.isna()
        if werte.dtype == object:
            maske |= werte.astype(str).str.strip().eq("")
        teile.append(verstoesse(gdf, maske, feld))
    return Ergebnis(geprueft=len(gdf), verstoesse=zusammenfuegen(teile))
