# -*- coding: utf-8 -*-
"""
datasets.py
--------------------------------------------------------------------
Die geprüften Datensätze, ihre Dateien und ihre stabilen Objektschlüssel.

Kürzel (wie in VALIDIERUNG_OFFEN.md):
- B  = snapping_converted_bikelanes (Radverkehrsanlagen je Kante, konvertiert)
- C  = aggregated_rvn_final (aggregiert, Layer hinrichtung/gegenrichtung)
- K  = Knotenpunkte, Abgabestand (knotenpunkte/output/knotenpunkte_abgabe.gpkg)
- VK = Verzeichnis der virtuellen Knotenpunkte (data/Virtuelle-Knotenpunkte.gpkg)

Der Schlüssel `_key` muss über Läufe hinweg gleich bleiben, damit der Diff
neue und behobene Verstöße erkennt. Zeilennummern (afid, sfid, Index) taugen
dafür nicht. Kommt ein Schlüssel mehrfach vor, wird er mit #2, #3 …
nach Lage (Bounding Box) durchnummeriert.
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .framework import EingabeFehlt

PROCESSING_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = PROCESSING_DIR.parent

sys.path.insert(0, str(PROCESSING_DIR))
sys.path.insert(0, str(REPO_DIR / "data"))
from helpers.clipping import clip_to_region  # noqa: E402
from helpers.globals import DEFAULT_CRS  # noqa: E402
from helpers.netz import datei_zusatz  # noqa: E402
import virtuelle_knotenpunkte as vk  # noqa: E402

DATENSAETZE = {
    "B": "Radverkehrsanlagen (snapping_converted_bikelanes)",
    "C": "Aggregiertes Netz (aggregated_rvn_final)",
    "K": "Knotenpunkte (knotenpunkte_abgabe)",
    "VK": "Virtuelle Knotenpunkte (Verzeichnis)",
}

KP_ID = "Knotenpunkt‐ID"  # Achtung: Bindestrich ist U+2010, nicht ASCII


def stabile_schluessel(gdf, teile):
    """Schlüssel aus Spalten (Liste) bzw. Funktion; Dubletten werden nach Lage durchnummeriert."""
    key = teile(gdf) if callable(teile) else gdf[teile].astype(str).agg(" ".join, axis=1)
    key = key.astype(str)
    if key.duplicated().any():
        if isinstance(gdf, gpd.GeoDataFrame):
            b = gdf.geometry.bounds
            order = pd.concat([key.rename("k"), b.round(1)], axis=1)
            n = order.sort_values(["k", "minx", "miny", "maxx", "maxy"], kind="stable").groupby("k").cumcount() + 1
        else:
            n = key.groupby(key).cumcount() + 1
        n = n.reindex(key.index)
        key = key.where(n == 1, key + "#" + n.astype(str))
    return key


def _relativ(path):
    try:
        return str(Path(path).resolve().relative_to(REPO_DIR))
    except ValueError:
        return str(path)


def fingerabdruck(path):
    """Größe, Änderungszeit und Hash einer Datei; damit sieht der Diff, ob sich Eingaben geändert haben."""
    p = Path(path)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    stat = p.stat()
    return {
        "pfad": _relativ(p),
        "bytes": stat.st_size,
        "geaendert": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "sha256": h.hexdigest()[:16],
    }


@dataclass
class Kontext:
    netz: str
    clip: str | None
    output_dir: Path
    eingaben: dict = field(default_factory=dict)  # Name -> Fingerabdruck (+ Objekte)
    _cache: dict = field(default_factory=dict, repr=False)

    def eingabe(self, name, path):
        """Pfad einer Eingabedatei; meldet sie für die Lauf-Metadaten an. Fehlt sie: EingabeFehlt."""
        p = Path(path)
        if not p.exists():
            raise EingabeFehlt(_relativ(p))
        if name not in self.eingaben:
            self.eingaben[name] = fingerabdruck(p)
        return p

    def datensatz(self, ds):
        """GeoDataFrame des Datensatzes mit Spalte `_key`; je Lauf nur einmal geladen."""
        if ds not in self._cache:
            try:
                gdf = LADER[ds](self)
            except EingabeFehlt as e:
                self._cache[ds] = e
                raise
            self._cache[ds] = gdf
            self.eingaben[ds]["objekte"] = len(gdf)
        if isinstance(self._cache[ds], Exception):
            raise self._cache[ds]
        return self._cache[ds]


def _lade_b(ctx):
    zusatz = datei_zusatz(ctx.netz, ctx.clip)
    path = ctx.output_dir / f"snapping_converted_bikelanes{zusatz}.fgb"
    if ctx.clip and not path.exists():
        # wie bisher: fehlt die zugeschnittene Datei, wird die vollständige dynamisch zugeschnitten
        path = ctx.output_dir / f"snapping_converted_bikelanes{datei_zusatz(ctx.netz)}.fgb"
        gdf = gpd.read_file(ctx.eingabe("B", path))
        gdf = clip_to_region(gdf, data_dir=str(PROCESSING_DIR / "data"), crs=f"EPSG:{DEFAULT_CRS}", region=ctx.clip)
        ctx.eingaben["B"]["zugeschnitten_auf"] = ctx.clip
    else:
        gdf = gpd.read_file(ctx.eingabe("B", path))
    gdf["_key"] = stabile_schluessel(
        gdf, lambda g: g["element_nr"].astype(str) + " ri=" + g["ri"].astype(str) + " " + g["tilda_id"].astype(str))
    return gdf


def _lade_c(ctx):
    path = ctx.eingabe("C", ctx.output_dir / f"aggregated_rvn_final{datei_zusatz(ctx.netz, ctx.clip)}.gpkg")
    teile = []
    for layer in ["hinrichtung", "gegenrichtung"]:
        g = gpd.read_file(path, layer=layer)
        g["_layer"] = layer
        teile.append(g)
    gdf = gpd.GeoDataFrame(pd.concat(teile, ignore_index=True), crs=teile[0].crs)
    gdf["_key"] = stabile_schluessel(
        gdf, lambda g: g["element_nr"].astype(str) + " ri=" + g["ri"].astype(str))
    return gdf


# Abgabestand der Knotenpunkt-Pipeline (knotenpunkte/README.md); hängt nicht von --netz/--clip/--output-dir ab
KNOTENPUNKTE_PATH = REPO_DIR / "knotenpunkte" / "output" / "knotenpunkte_abgabe.gpkg"


def _lade_k(ctx):
    gdf = gpd.read_file(ctx.eingabe("K", KNOTENPUNKTE_PATH))
    gdf["_key"] = stabile_schluessel(gdf, lambda g: g[KP_ID].fillna("ohne ID").astype(str))
    return gdf


def _lade_vk(ctx):
    gdf = vk.read_all(ctx.eingabe("VK", vk.PATH))
    gdf["_key"] = stabile_schluessel(gdf, lambda g: g[vk.ID_COLUMN].fillna("ohne Nummer").astype(str))
    return gdf


LADER = {"B": _lade_b, "C": _lade_c, "K": _lade_k, "VK": _lade_vk}


def git_stand():
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO_DIR), *args], capture_output=True, text=True).stdout.strip()
    try:
        return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except OSError:
        return {"commit": None, "dirty": None}
