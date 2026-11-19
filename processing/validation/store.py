# -*- coding: utf-8 -*-
"""
store.py
--------------------------------------------------------------------
Ablage der Läufe. Jeder Lauf ist ein Ordner unter validation/runs/:

    runs/20261118-143012_ren/
        run.json                 Metadaten (Netz, Zuschnitt, Commit, Eingaben mit Hash) und Ergebnis je Prüfung
        verstoesse/<ID>.csv      alle Verstöße der Prüfung (objekt, detail), sortiert – Grundlage des Diffs
        verstoesse.gpkg          ein Layer je Prüfung mit Geometrie, zur Kontrolle in QGIS

Läufe werden nie überschrieben. Ihre Nummer (#1, #2, …) ergibt sich aus der
zeitlichen Reihenfolge aller Läufe.
"""

import json
import warnings
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path

import geopandas as gpd
import pandas as pd

RUNS_DIR = Path(__file__).resolve().parent / "runs"


@dataclass
class Lauf:
    nr: int
    ordner: Path

    @cached_property
    def meta(self):
        return json.loads((self.ordner / "run.json").read_text(encoding="utf-8"))

    @property
    def id(self):
        return self.ordner.name

    @property
    def ergebnisse(self):
        return {e["id"]: e for e in self.meta["ergebnisse"]}

    @property
    def zeit(self):
        return datetime.fromisoformat(self.meta["zeit"])

    @property
    def variante(self):
        """Netz und Zuschnitt; nur Läufe derselben Variante sind direkt vergleichbar."""
        return (self.meta["netz"], self.meta.get("clip"))

    def verstoesse(self, check_id):
        """Menge der (objekt, detail)-Paare einer Prüfung."""
        path = self.ordner / "verstoesse" / f"{check_id}.csv"
        if not path.exists():
            return set()
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        return set(zip(df["objekt"], df["detail"]))


def speichern(meta, ergebnisse):
    """Legt einen neuen Lauf an und gibt ihn zurück."""
    stempel = datetime.fromisoformat(meta["zeit"]).strftime("%Y%m%d-%H%M%S")
    name = "_".join(x for x in [stempel, meta["netz"], meta.get("clip")] if x)
    ordner = RUNS_DIR / name
    ordner.mkdir(parents=True, exist_ok=False)
    (ordner / "verstoesse").mkdir()

    gpkg = ordner / "verstoesse.gpkg"
    for e in ergebnisse:
        df = e.verstoesse
        if df is None or not len(df):
            continue
        df[["objekt", "detail"]].to_csv(ordner / "verstoesse" / f"{e.id}.csv", index=False)
        if isinstance(df, gpd.GeoDataFrame) and df.geometry.notna().any():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df[df.geometry.notna()].to_file(gpkg, layer=e.id, driver="GPKG")

    meta = {**meta, "ergebnisse": [e.als_dict() for e in ergebnisse]}
    (ordner / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return next(l for l in alle_laeufe() if l.ordner == ordner)


def alle_laeufe():
    if not RUNS_DIR.exists():
        return []
    ordner = sorted(p for p in RUNS_DIR.iterdir() if (p / "run.json").exists())
    return [Lauf(i + 1, p) for i, p in enumerate(ordner)]


def finde(ref, laeufe=None):
    """Lauf nach Nummer (7), relativ (-1 = neuester) oder Ordnername (auch Präfix)."""
    laeufe = laeufe if laeufe is not None else alle_laeufe()
    if not laeufe:
        raise SystemExit("Noch keine gespeicherten Läufe.")
    ref = str(ref).lstrip("#")
    try:
        n = int(ref)
        if n < 0:
            return laeufe[n]
        return next(l for l in laeufe if l.nr == n)
    except (ValueError, IndexError, StopIteration):
        pass
    treffer = [l for l in laeufe if l.id.startswith(ref)]
    if len(treffer) == 1:
        return treffer[0]
    raise SystemExit(f"Lauf „{ref}“ nicht gefunden ({len(treffer)} Treffer). `list` zeigt alle Läufe.")


def vorgaenger(lauf):
    """Letzter vollständiger Lauf (ohne --nur) derselben Variante vor diesem Lauf, oder None."""
    frueher = [l for l in alle_laeufe()
               if l.nr < lauf.nr and l.variante == lauf.variante and not l.meta.get("auswahl")]
    return frueher[-1] if frueher else None
