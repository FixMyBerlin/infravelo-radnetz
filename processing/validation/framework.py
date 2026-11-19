# -*- coding: utf-8 -*-
"""
framework.py
--------------------------------------------------------------------
Kern der Validierung: Prüfungen registrieren, ausführen, Status bestimmen.

Eine Prüfung ist eine Funktion (ctx, ds) -> Ergebnis, registriert mit @pruefung.
Sie meldet, wie viele Objekte sie geprüft hat, und die Verstöße als Tabelle mit
den Spalten `objekt` (stabiler Schlüssel des Objekts), `detail` (z. B. das
betroffene Attribut) und optional `geometry`. Die Paare (objekt, detail) sind
die Einheit, über die zwei Läufe verglichen werden.
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

import geopandas as gpd
import pandas as pd

FEHLER = "fehler"
WARNUNG = "warnung"

# Status einer Prüfung in einem Lauf
OK = "ok"
FAIL = "fail"
WARN = "warn"
ERROR = "error"  # Prüfung konnte nicht laufen (Eingabe fehlt, Ausnahme)


class EingabeFehlt(Exception):
    """Eine Eingabedatei der Prüfung existiert nicht."""


@dataclass
class Ergebnis:
    geprueft: int  # Anzahl geprüfter Objekte
    verstoesse: pd.DataFrame = None  # Spalten objekt, detail[, geometry]

    def __post_init__(self):
        if self.verstoesse is None:
            self.verstoesse = keine_verstoesse()


@dataclass
class Pruefung:
    id: str
    name: str
    datensatz: str
    schwere: str
    regel: str
    fn: Callable = field(repr=False)


REGISTRY: dict[str, Pruefung] = {}


def pruefung(slug, name, regel, datensaetze, schwere=FEHLER):
    """Registriert eine Prüfung für einen oder mehrere Datensätze; ID = <Datensatz>-<slug>."""
    if isinstance(datensaetze, str):
        datensaetze = [datensaetze]

    def decorator(fn):
        for ds in datensaetze:
            check_id = f"{ds}-{slug}"
            if check_id in REGISTRY:
                raise ValueError(f"Prüfung {check_id} doppelt registriert")
            REGISTRY[check_id] = Pruefung(check_id, name, ds, schwere, regel, fn)
        return fn

    return decorator


def keine_verstoesse():
    return pd.DataFrame({"objekt": pd.Series(dtype=str), "detail": pd.Series(dtype=str)})


def verstoesse(gdf, maske=None, detail=""):
    """Verstöße aus den Zeilen von gdf (Spalte `_key`), auf die maske zutrifft.

    detail ist ein fester Text oder eine Series (z. B. der gefundene Wert).
    """
    rows = gdf if maske is None else gdf[maske]
    data = {"objekt": rows["_key"].astype(str).values}
    data["detail"] = detail.loc[rows.index].astype(str).values if isinstance(detail, pd.Series) else detail
    df = pd.DataFrame(data, index=rows.index)
    if isinstance(rows, gpd.GeoDataFrame) and rows.geometry.name in rows:
        return gpd.GeoDataFrame(df, geometry=rows.geometry.values, crs=rows.crs)
    return df


def zusammenfuegen(teile):
    """Mehrere Verstoß-Tabellen zu einer; Geometrie bleibt erhalten, wenn vorhanden."""
    teile = [t for t in teile if t is not None and len(t)]
    if not teile:
        return keine_verstoesse()
    geo = [t for t in teile if isinstance(t, gpd.GeoDataFrame)]
    df = pd.concat(teile, ignore_index=True)
    if geo:
        return gpd.GeoDataFrame(df, geometry="geometry", crs=geo[0].crs)
    return df


@dataclass
class PruefErgebnis:
    """Ergebnis einer Prüfung in einem Lauf, so wie es gespeichert wird."""
    id: str
    name: str
    datensatz: str
    schwere: str
    regel: str
    status: str
    geprueft: int = 0
    anzahl: int = 0  # Verstöße, also Paare (objekt, detail)
    objekte: int = 0  # betroffene Objekte
    meldung: str = ""
    dauer_s: float = 0.0
    verstoesse: pd.DataFrame = field(default=None, repr=False)

    def als_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != "verstoesse"}


def status_fuer(schwere, anzahl):
    if anzahl == 0:
        return OK
    return FAIL if schwere == FEHLER else WARN


def ausfuehren(ctx, auswahl=None, fortschritt=None):
    """Führt alle (oder die ausgewählten) Prüfungen aus; eine fehlerhafte Prüfung hält die anderen nicht auf."""
    ergebnisse = []
    for check in sorted(REGISTRY.values(), key=lambda c: c.id):
        if auswahl and not any(check.id.startswith(a) for a in auswahl):
            continue
        if fortschritt:
            fortschritt(check)
        start = time.perf_counter()
        basis = dict(id=check.id, name=check.name, datensatz=check.datensatz,
                     schwere=check.schwere, regel=check.regel)
        try:
            res = check.fn(ctx, check.datensatz)
            df = res.verstoesse.drop_duplicates(subset=["objekt", "detail"])
            df = df.sort_values(["objekt", "detail"]).reset_index(drop=True)
            pe = PruefErgebnis(**basis, status=status_fuer(check.schwere, len(df)),
                               geprueft=int(res.geprueft), anzahl=len(df),
                               objekte=int(df["objekt"].nunique()), verstoesse=df)
        except EingabeFehlt as e:
            pe = PruefErgebnis(**basis, status=ERROR, meldung=f"Eingabe fehlt: {e}")
        except Exception as e:  # noqa: BLE001 – jede Ausnahme wird als Ergebnis gemeldet
            letzte = traceback.extract_tb(e.__traceback__)[-1]
            pe = PruefErgebnis(**basis, status=ERROR,
                               meldung=f"{type(e).__name__}: {e} ({letzte.filename.split('/')[-1]}:{letzte.lineno})")
        pe.dauer_s = round(time.perf_counter() - start, 2)
        ergebnisse.append(pe)
    return ergebnisse
