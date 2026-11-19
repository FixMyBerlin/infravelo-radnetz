# -*- coding: utf-8 -*-
"""
Prüfungen des Verzeichnisses der virtuellen Knotenpunkte (VK).

Übernommen aus validate_virtuelle_knotenpunkte.py. Die Regeln selbst stehen in
data/virtuelle_knotenpunkte.py (regelverstoesse) und data/VIRTUELLE-KNOTENPUNKTE.md.
"""

import geopandas as gpd
import pandas as pd

from ..datasets import REPO_DIR, vk
from ..framework import WARNUNG, Ergebnis, pruefung

REN_PATH = REPO_DIR / "ren-network" / "output" / "ren_netz_gesamt.gpkg"
REN_LAYER = "ren_netz"
AUF_KANTE_TOLERANZ_M = 3.0  # wie VIRTUAL_NODE_TOLERANCE in split_rvn_at_virtual_nodes.py


@pruefung("REGELN", "Verzeichnis folgt den Regeln", datensaetze="VK",
          regel="Nummer 4-stellig und eindeutig (auch gelöschte), status aktiv/geloescht, Gelöschte mit "
                "Datum und Grund, alte_id und App-Quelle eindeutig, Geometrie vorhanden. Detail = Regel.")
def regeln(ctx, ds):
    gdf = ctx.datensatz(ds)
    zeilen = [(eintrag, regel) for regel, eintraege in vk.regelverstoesse(gdf) for eintrag in eintraege]
    return Ergebnis(geprueft=len(gdf), verstoesse=pd.DataFrame(zeilen, columns=["objekt", "detail"]))


@pruefung("ALT-NEU", "Zuordnung alt → neu passt zum Verzeichnis", datensaetze="VK",
          regel="Jede Zeile in data/virtuelle_knotenpunkte_alt_neu.csv stimmt mit alte_id im Verzeichnis überein. "
                "Objekt = alte ID, Detail = erwartete neue Nummer.")
def alt_neu(ctx, ds):
    gdf = ctx.datensatz(ds)
    tabelle = pd.read_csv(ctx.eingabe("VK_alt_neu", vk.OLD_TO_NEW_PATH), dtype=str)
    im_verzeichnis = dict(zip(gdf["alte_id"], gdf[vk.ID_COLUMN]))
    falsch = [(r.alte_id, f"→ {r.neue_id}, im Verzeichnis {im_verzeichnis.get(r.alte_id)}")
              for r in tabelle.itertuples() if im_verzeichnis.get(r.alte_id) != r.neue_id]
    return Ergebnis(geprueft=len(tabelle), verstoesse=pd.DataFrame(falsch, columns=["objekt", "detail"]))


@pruefung("AUF-REN", "Aktive Knoten liegen auf dem REN+", datensaetze="VK", schwere=WARNUNG,
          regel=f"Jeder aktive Knoten liegt höchstens {AUF_KANTE_TOLERANZ_M:g} m von einer Kante des REN+ "
                "entfernt. Warnung: Knoten auf neuen Kanten der Netzanpassungen-App liegen dort erst, "
                "wenn die Kanten im REN+ sind. Detail = quelle.")
def auf_ren(ctx, ds):
    gdf = ctx.datensatz(ds)
    aktiv = gdf[gdf["status"] == vk.STATUS_ACTIVE]
    netz = gpd.read_file(ctx.eingabe("REN+", REN_PATH), layer=REN_LAYER, columns=["element_nr"]).to_crs(vk.CRS)
    puffer = aktiv[["_key", "geometry"]].set_geometry(aktiv.buffer(AUF_KANTE_TOLERANZ_M))
    nah = gpd.sjoin(puffer, netz[["geometry"]], predicate="intersects")
    weg = aktiv[~aktiv["_key"].isin(nah["_key"])]
    df = gpd.GeoDataFrame({"objekt": weg["_key"].values, "detail": weg["quelle"].fillna("").values},
                          geometry=weg.geometry.values, crs=gdf.crs)
    return Ergebnis(geprueft=len(aktiv), verstoesse=df)
