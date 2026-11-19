# -*- coding: utf-8 -*-
"""
Prüfungen über Kanten und ihre Richtungen.

Übernommen aus validate_datensatz_b.py: doppelte tilda_id bei entgegengesetzten
Einrichtungsverkehr-Kanten.
"""

import geopandas as gpd
import pandas as pd

from ..framework import Ergebnis, pruefung


@pruefung("TILDA-RICHTUNG", "Eigene TILDA-Quelle je Fahrtrichtung", datensaetze="B",
          regel="Bei verkehrsri = Einrichtungsverkehr haben ri=0 und ri=1 derselben element_nr "
                "keine gemeinsame tilda_id. Objekt = element_nr, Detail = doppelte tilda_id.")
def tilda_id_je_richtung(ctx, ds):
    gdf = ctx.datensatz(ds)
    e = gdf[(gdf["verkehrsri"] == "Einrichtungsverkehr") & gdf["tilda_id"].notna()].copy()
    e["_ri"] = pd.to_numeric(e["ri"], errors="coerce")
    cols = ["element_nr", "tilda_id"]
    doppelt = e[e["_ri"] == 0][cols].drop_duplicates().merge(e[e["_ri"] == 1][cols].drop_duplicates())
    rows = e.merge(doppelt, on=cols).drop_duplicates(cols)
    df = gpd.GeoDataFrame({"objekt": rows["element_nr"].astype(str).values,
                           "detail": rows["tilda_id"].astype(str).values},
                          geometry=rows.geometry.values, crs=gdf.crs)
    return Ergebnis(geprueft=e["element_nr"].nunique(), verstoesse=df)
