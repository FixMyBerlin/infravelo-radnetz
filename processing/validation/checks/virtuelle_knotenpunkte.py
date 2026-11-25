# -*- coding: utf-8 -*-
"""
Prüfungen der virtuellen Knotenpunkte (VK).

Übernommen aus validate_virtuelle_knotenpunkte.py. Geprüft wird die Ausgabe von Schritt 3
(netzanpassungen/output/virtuelle_knoten.gpkg: die 53 von 2025 und alle Knoten der App
Netzanpassungen), dazu das Archiv der 53 von 2025 (netzanpassungen/one_time_import/2025/).
Die Regeln selbst stehen in data/virtuelle_knotenpunkte.py (rule_violations,
check_registry_frozen) und data/VIRTUELLE-KNOTENPUNKTE.md.
"""

import geopandas as gpd
import pandas as pd

from ..datasets import REPO_DIR, vk
from ..framework import WARNUNG, Ergebnis, pruefung

REN_PATH = REPO_DIR / "ren-network" / "output" / "ren_netz.gpkg"
REN_LAYER = "ren_netz"
AUF_KANTE_TOLERANZ_M = 3.0  # wie VIRTUAL_NODE_TOLERANCE in split_rvn_at_virtual_nodes.py


def _archiv(ctx):
    return vk.read_all(ctx.eingabe("VK_archiv_2025", vk.ARCHIVE_PATH))


@pruefung("REGELN", "Knoten folgen den Regeln", datensaetze="VK",
          regel="Nummer 4-stellig und eindeutig (auch gelöschte), status aktiv/geloescht, Gelöschte mit "
                "Datum und Grund, id_rvn_2025 und App-Eintrag eindeutig, Geometrie vorhanden. Detail = Regel.")
def regeln(ctx, ds):
    gdf = ctx.datensatz(ds)
    zeilen = [(eintrag, regel) for regel, eintraege in vk.rule_violations(gdf) for eintrag in eintraege]
    return Ergebnis(geprueft=len(gdf), verstoesse=pd.DataFrame(zeilen, columns=["objekt", "detail"]))


@pruefung("ARCHIV-2025", "Archiv der 53 von 2025 unverändert", datensaetze="VK",
          regel="Das Archiv netzanpassungen/one_time_import/2025/Virtuelle-Knotenpunkte.gpkg folgt den Regeln "
                f"und enthält genau die {vk.REGISTRY_SIZE} aktiven Knoten 0001-{vk.REGISTRY_SIZE:04d}, jeder mit "
                "id_rvn_2025. Neue Knoten entstehen nur in der App. Objekt = Archivdatei, Detail = Regel.")
def archiv_2025(ctx, ds):
    archiv = _archiv(ctx)
    fehler = vk.check(archiv) + vk.check_registry_frozen(archiv)
    zeilen = [(vk.ARCHIVE_PATH.name, f) for f in fehler]
    return Ergebnis(geprueft=len(archiv), verstoesse=pd.DataFrame(zeilen, columns=["objekt", "detail"]))


@pruefung("2025-VORHANDEN", "Knoten von 2025 in der Ausgabe", datensaetze="VK",
          regel="Jeder der 53 Knoten des Archivs von 2025 steht in der Ausgabe von Schritt 3. "
                "Objekt = Nummer, Detail = id_rvn_2025.")
def vorhanden_2025(ctx, ds):
    gdf = ctx.datensatz(ds)
    archiv = _archiv(ctx)
    fehlt = archiv[~archiv[vk.ID_COLUMN].isin(gdf[vk.ID_COLUMN])]
    df = pd.DataFrame({"objekt": fehlt[vk.ID_COLUMN].values, "detail": fehlt["id_rvn_2025"].fillna("").values})
    return Ergebnis(geprueft=len(archiv), verstoesse=df)


@pruefung("ALT-NEU", "Zuordnung alt → neu passt zum Archiv", datensaetze="VK",
          regel="Jede Zeile in data/virtuelle_knotenpunkte_alt_neu.csv stimmt mit id_rvn_2025 im Archiv von "
                "2025 überein. Objekt = id_rvn_2025, Detail = erwartete neue Nummer.")
def alt_neu(ctx, ds):
    archiv = _archiv(ctx)
    tabelle = pd.read_csv(ctx.eingabe("VK_alt_neu", vk.OLD_TO_NEW_PATH), dtype=str)
    im_archiv = dict(zip(archiv["id_rvn_2025"], archiv[vk.ID_COLUMN]))
    falsch = [(r.id_rvn_2025, f"→ {r.neue_id}, im Archiv {im_archiv.get(r.id_rvn_2025)}")
              for r in tabelle.itertuples() if im_archiv.get(r.id_rvn_2025) != r.neue_id]
    return Ergebnis(geprueft=len(tabelle), verstoesse=pd.DataFrame(falsch, columns=["objekt", "detail"]))


@pruefung("AUF-REN", "Aktive Knoten liegen auf dem REN+", datensaetze="VK", schwere=WARNUNG,
          regel=f"Jeder aktive Knoten liegt höchstens {AUF_KANTE_TOLERANZ_M:g} m von einer Kante des REN+ "
                "(ren-network/output/ren_netz.gpkg) entfernt. Warnung, z. B. nach einem neuen Detailnetz. "
                "Gegen das Detailnetz wird nicht geprüft: Viele Knoten von 2025 liegen auf der Geometrie des "
                "Radvorrangnetzes, die bis zu 300 m davon abweicht. Detail = quelle.")
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
