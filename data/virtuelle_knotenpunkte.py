#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
virtuelle_knotenpunkte.py
--------------------------------------------------------------------
Verzeichnis der virtuellen Knotenpunkte: data/Virtuelle-Knotenpunkte.gpkg.
Die Regeln stehen in data/VIRTUELLE-KNOTENPUNKTE.md.

Nur dieses Skript vergibt Nummern. Neue Punkte werden in QGIS ohne ID angelegt
oder mit `uebernehmen` aus dem Export der Netzanpassungen-App geholt; danach
vergibt `nummerieren` die nächsten freien Nummern.

Als Modul: read_active() liefert die aktiven Knoten für die Pipeline,
read_all() alle Zeilen einschließlich der gelöschten.

Aufruf (im Projekt-Root):
    .venv/bin/python data/virtuelle_knotenpunkte.py pruefen
    .venv/bin/python data/virtuelle_knotenpunkte.py nummerieren
    .venv/bin/python data/virtuelle_knotenpunkte.py uebernehmen <netzanpassungen-virtuelle-knoten-….geojson>
    .venv/bin/python data/virtuelle_knotenpunkte.py loeschen 0012 --grund "Kante entfallen"
    .venv/bin/python data/virtuelle_knotenpunkte.py umnummerieren   # einmalig, altes Schema -> neues
"""

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
PATH = DATA_DIR / "Virtuelle-Knotenpunkte.gpkg"
LAYER = "Virtuelle-Knotenpunkte"
OLD_TO_NEW_PATH = DATA_DIR / "virtuelle_knotenpunkte_alt_neu.csv"
CRS = "EPSG:25833"

ID_COLUMN = "Knotenpunkt-ID"  # mit ASCII-Bindestrich, wie seit 2025 in dieser Datei
ID_PATTERN = re.compile(r"^\d{4}$")
ID_DIGITS = 4
STATUS_ACTIVE = "aktiv"
STATUS_DELETED = "geloescht"
APP_SOURCE_PREFIX = "app:"

COLUMNS = [ID_COLUMN, "ist_virtuell", "status", "angelegt_am", "geloescht_am", "grund",
           "alte_id", "quelle", "kommentar"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _text(value):
    """IDs und Texte immer als str; leere Werte als None. 12.0 -> '12' (führende Nullen ergänzt pad_id)."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def pad_id(value):
    """'12' -> '0012'. Andere Werte bleiben, wie sie sind, und fallen in pruefen auf."""
    text = _text(value)
    if text is not None and text.isdigit() and len(text) < ID_DIGITS:
        return text.zfill(ID_DIGITS)
    return text


def read_all(path=PATH):
    """Alle Zeilen des Verzeichnisses, gelöschte eingeschlossen, in EPSG:25833."""
    gdf = gpd.read_file(path, layer=LAYER)
    if gdf.crs is None or gdf.crs.to_string() != CRS:
        gdf = gdf.to_crs(CRS)
    for column in COLUMNS:
        if column not in gdf.columns:
            gdf[column] = None
    gdf[ID_COLUMN] = gdf[ID_COLUMN].map(pad_id)
    for column in ["status", "angelegt_am", "geloescht_am", "grund", "alte_id", "quelle", "kommentar"]:
        gdf[column] = gdf[column].map(_text)
    return gdf


def read_active(path=PATH):
    """Aktive virtuelle Knoten mit Nummer. Bricht ab, wenn das Verzeichnis gegen die Regeln verstößt."""
    gdf = read_all(path)
    errors = check(gdf)
    if errors:
        raise ValueError("Virtuelle-Knotenpunkte.gpkg verstößt gegen die Regeln "
                         "(data/VIRTUELLE-KNOTENPUNKTE.md):\n- " + "\n- ".join(errors))
    active = gdf[gdf["status"] == STATUS_ACTIVE].reset_index(drop=True)
    active["ist_virtuell"] = 1
    logging.info(f"Virtuelle Knotenpunkte: {len(active)} aktiv, {len(gdf) - len(active)} gelöscht")
    return active


def old_to_new(path=PATH):
    """Alte ID (z. B. 'V44530016-44530064') -> heutige Nummer, für Daten aus der Zeit vor der Umnummerierung."""
    gdf = read_all(path)
    known = gdf[gdf["alte_id"].notna()]
    return dict(zip(known["alte_id"], known[ID_COLUMN]))


def translate_element_nr(element_nr, mapping=None):
    """Alte V-Kennungen in einer element_nr durch die Nummern ersetzen:
    'V6475_V4789.01' -> '0039_0022.01'. Andere element_nr bleiben unverändert."""
    if not isinstance(element_nr, str):
        return element_nr
    mapping = old_to_new() if mapping is None else mapping
    match = re.match(r"^(.+?)_(.+)(\.\d+)$", element_nr)
    if not match:
        return element_nr
    von, bis, suffix = match.groups()
    return f"{mapping.get(von, von)}_{mapping.get(bis, bis)}{suffix}"


def check(gdf):
    """Regelverstöße als Liste von Sätzen; leer, wenn alles stimmt."""
    errors = []
    numbered = gdf[gdf[ID_COLUMN].notna()]
    bad = numbered[~numbered[ID_COLUMN].str.match(ID_PATTERN)]
    if len(bad):
        errors.append(f"Nummer nicht 4-stellig: {sorted(bad[ID_COLUMN])}")
    duplicated = numbered[ID_COLUMN][numbered[ID_COLUMN].duplicated()]
    if len(duplicated):
        errors.append(f"Nummer mehrfach vergeben (auch gelöschte zählen): {sorted(set(duplicated))}")
    unnumbered = gdf[gdf[ID_COLUMN].isna()]
    if len(unnumbered):
        errors.append(f"{len(unnumbered)} Punkt(e) ohne Nummer, erst `nummerieren` ausführen")
    status = gdf[~gdf["status"].isin([STATUS_ACTIVE, STATUS_DELETED]) & gdf[ID_COLUMN].notna()]
    if len(status):
        errors.append(f"status muss '{STATUS_ACTIVE}' oder '{STATUS_DELETED}' sein: {sorted(status[ID_COLUMN])}")
    deleted = gdf[gdf["status"] == STATUS_DELETED]
    no_date = deleted[deleted["geloescht_am"].isna() | deleted["grund"].isna()]
    if len(no_date):
        errors.append(f"Gelöscht ohne geloescht_am oder grund: {sorted(no_date[ID_COLUMN])}")
    alte = gdf["alte_id"].dropna()
    if alte.duplicated().any():
        errors.append(f"alte_id mehrfach: {sorted(set(alte[alte.duplicated()]))}")
    app = gdf["quelle"].dropna()
    app = app[app.str.startswith(APP_SOURCE_PREFIX)]
    if app.duplicated().any():
        errors.append(f"App-Eintrag mehrfach übernommen: {sorted(set(app[app.duplicated()]))}")
    empty = gdf[gdf.geometry.isna() | gdf.geometry.is_empty]
    if len(empty):
        errors.append(f"Punkt(e) ohne Geometrie: {sorted(empty[ID_COLUMN].fillna('ohne Nummer'))}")
    return errors


def next_number(gdf):
    """Höchste je vergebene Nummer + 1; gelöschte Nummern zählen mit und werden nie wieder vergeben."""
    numbers = gdf[ID_COLUMN].dropna()
    numbers = numbers[numbers.str.match(ID_PATTERN)].astype(int)
    return (numbers.max() if len(numbers) else 0) + 1


def write(gdf, path=PATH):
    gdf = gdf[COLUMNS + ["geometry"]].copy()
    gdf["ist_virtuell"] = 1
    for column in COLUMNS:
        if column != "ist_virtuell":
            gdf[column] = gdf[column].astype("string")
    gdf = gdf.sort_values(ID_COLUMN, na_position="last", kind="stable").reset_index(drop=True)
    gdf.set_crs(CRS, allow_override=True).to_file(path, layer=LAYER, driver="GPKG")
    logging.info(f"Geschrieben: {path} ({len(gdf)} Zeilen)")


def number_new(gdf, today=None):
    """Vergibt Nummern an Punkte ohne Nummer, in der Reihenfolge der Datei (fid)."""
    today = today or date.today().isoformat()
    gdf = gdf.copy()
    new = gdf.index[gdf[ID_COLUMN].isna()]
    start = next_number(gdf)
    if start + len(new) - 1 > 10 ** ID_DIGITS - 1:
        raise ValueError(f"Nummernkreis {ID_DIGITS}-stellig erschöpft")
    for offset, index in enumerate(new):
        gdf.loc[index, ID_COLUMN] = str(start + offset).zfill(ID_DIGITS)
        gdf.loc[index, "status"] = _text(gdf.loc[index, "status"]) or STATUS_ACTIVE
        gdf.loc[index, "angelegt_am"] = _text(gdf.loc[index, "angelegt_am"]) or today
        gdf.loc[index, "quelle"] = _text(gdf.loc[index, "quelle"]) or "QGIS"
    if len(new):
        logging.info(f"Neue Nummern: {', '.join(gdf.loc[new, ID_COLUMN])}")
    else:
        logging.info("Keine Punkte ohne Nummer")
    return gdf


def cmd_pruefen(_args):
    gdf = read_all()
    errors = check(gdf)
    active = (gdf["status"] == STATUS_ACTIVE).sum()
    logging.info(f"{len(gdf)} Zeilen, {active} aktiv, nächste Nummer {str(next_number(gdf)).zfill(ID_DIGITS)}")
    for error in errors:
        logging.error(error)
    return 1 if errors else 0


def cmd_nummerieren(_args):
    gdf = number_new(read_all())
    errors = check(gdf)
    if errors:
        for error in errors:
            logging.error(error)
        return 1
    write(gdf)
    return 0


def cmd_uebernehmen(args):
    """Hängt virtuelle Knoten aus dem App-Export an, die noch nicht übernommen sind, und nummeriert sie."""
    gdf = read_all()
    app = gpd.read_file(args.datei).to_crs(CRS)
    if "app_eintrag" not in app.columns:
        logging.error("Export ohne Spalte app_eintrag; mit der aktuellen Netzanpassungen-App neu exportieren")
        return 1
    known = set(gdf["quelle"].dropna())
    rows = []
    for _, feature in app.iterrows():
        source = f"{APP_SOURCE_PREFIX}{feature['app_eintrag']}"
        if source in known:
            continue
        if _text(feature.get(ID_COLUMN)):
            logging.warning(f"{source} hat schon Nummer {feature[ID_COLUMN]}, steht aber nicht im Verzeichnis; übersprungen")
            continue
        rows.append({ID_COLUMN: None, "ist_virtuell": 1, "status": STATUS_ACTIVE, "angelegt_am": None,
                     "geloescht_am": None, "grund": None, "alte_id": None, "quelle": source,
                     "kommentar": _text(feature.get("kommentar")), "geometry": feature.geometry})
    logging.info(f"Aus der App: {len(app)} Knoten, davon {len(rows)} neu")
    if not rows:
        return 0
    gdf = pd.concat([gdf, gpd.GeoDataFrame(rows, crs=CRS)], ignore_index=True)
    gdf = number_new(gpd.GeoDataFrame(gdf, crs=CRS))
    errors = check(gdf)
    if errors:
        for error in errors:
            logging.error(error)
        return 1
    write(gdf)
    logging.info("Danach netzanpassungen/export_app_daten.py laufen lassen und die Datei in die App laden; "
                 "die App zeigt dann die Nummern.")
    return 0


def cmd_loeschen(args):
    gdf = read_all()
    node_id = pad_id(args.id)
    match = gdf.index[gdf[ID_COLUMN] == node_id]
    if len(match) != 1:
        logging.error(f"Nummer {node_id} nicht gefunden")
        return 1
    if gdf.loc[match[0], "status"] == STATUS_DELETED:
        logging.error(f"{node_id} ist schon gelöscht ({gdf.loc[match[0], 'geloescht_am']})")
        return 1
    gdf.loc[match[0], "status"] = STATUS_DELETED
    gdf.loc[match[0], "geloescht_am"] = date.today().isoformat()
    gdf.loc[match[0], "grund"] = args.grund
    write(gdf)
    logging.info(f"{node_id} gelöscht; die Nummer bleibt gesperrt")
    return 0


def cmd_umnummerieren(_args):
    """Einmalig: Schema bis 2026-11 (nur Knotenpunkt-ID mit V…) -> 4-stellige Nummern ab 0001.
    Reihenfolge: alte ID als Text sortiert. Die alte ID bleibt in alte_id, die Zuordnung zusätzlich
    in virtuelle_knotenpunkte_alt_neu.csv. Die alte Datei liegt in git (Commit e47bd61)."""
    raw = gpd.read_file(PATH)
    if "status" in raw.columns:
        logging.error("Das Verzeichnis hat schon das neue Schema; nichts zu tun")
        return 1
    raw = raw.to_crs(CRS)
    raw["alte_id"] = raw[ID_COLUMN].map(_text)
    raw = raw.sort_values("alte_id", kind="stable").reset_index(drop=True)
    raw[ID_COLUMN] = [str(number).zfill(ID_DIGITS) for number in range(1, len(raw) + 1)]
    raw["ist_virtuell"] = 1
    raw["status"] = STATUS_ACTIVE
    raw["angelegt_am"] = None
    raw["geloescht_am"] = None
    raw["grund"] = None
    raw["quelle"] = "Bestand (vor 2026-11 mit V-Kennung)"
    raw["kommentar"] = None
    gdf = gpd.GeoDataFrame(raw, crs=CRS)
    errors = check(gdf)
    if errors:
        for error in errors:
            logging.error(error)
        return 1
    write(gdf)
    gdf[["alte_id", ID_COLUMN]].rename(columns={ID_COLUMN: "neue_id"}).to_csv(OLD_TO_NEW_PATH, index=False)
    logging.info(f"Zuordnung alt -> neu: {OLD_TO_NEW_PATH}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Verzeichnis der virtuellen Knotenpunkte pflegen")
    sub = parser.add_subparsers(dest="befehl", required=True)
    sub.add_parser("pruefen", help="Regeln prüfen").set_defaults(func=cmd_pruefen)
    sub.add_parser("nummerieren", help="Punkten ohne Nummer die nächsten Nummern geben").set_defaults(func=cmd_nummerieren)
    app = sub.add_parser("uebernehmen", help="Neue virtuelle Knoten aus dem Export der Netzanpassungen-App übernehmen")
    app.add_argument("datei", help="GeoJSON aus der App (Export „Virtuelle Knoten“)")
    app.set_defaults(func=cmd_uebernehmen)
    delete = sub.add_parser("loeschen", help="Knoten als gelöscht markieren; die Nummer bleibt gesperrt")
    delete.add_argument("id")
    delete.add_argument("--grund", required=True)
    delete.set_defaults(func=cmd_loeschen)
    sub.add_parser("umnummerieren", help="Einmalig: V-Kennungen in 4-stellige Nummern umwandeln").set_defaults(
        func=cmd_umnummerieren)
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
