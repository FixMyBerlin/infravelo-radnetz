# -*- coding: utf-8 -*-
"""
pfade.py
Gemeinsame Pfade und Argumente der Analyse-Skripte.

Die Dateinamen folgen execute_processing.sh: Suffix = Netz (`_ren`, beim RVN leer) + Zuschnitt (`_<clip>`).
Wie die Pipeline gilt ohne `--netz` das REN+. Ordner je Netz kommen aus helpers/netz.py.

Verwendung in einem Analyse-Skript:

    from pfade import argumente, Pfade
    args = argumente("Was das Skript auswertet").parse_args()
    p = Pfade(args.netz, args.clip)
    gdf = gpd.read_file(p.snapping_enriched)
"""

import argparse
import sys
from pathlib import Path

PROCESSING = Path(__file__).resolve().parents[1]
if str(PROCESSING) not in sys.path:
    sys.path.insert(0, str(PROCESSING))

from helpers.netz import DEFAULT_NETZ, MATCHING_DIR, NETZE, TILDA_ROUTING_DIR  # noqa: E402

OUTPUT = PROCESSING / "output"
ANALYSIS_DIR = OUTPUT / "analysis"
CLIPS = ("neukoelln", "norden", "sueden")


def argumente(beschreibung: str) -> argparse.ArgumentParser:
    """Parser mit --netz und --clip; das Skript kann weitere Argumente ergänzen."""
    parser = argparse.ArgumentParser(description=beschreibung)
    parser.add_argument("--netz", choices=NETZE, default=DEFAULT_NETZ, help=f"Zielnetz (Standard: {DEFAULT_NETZ})")
    parser.add_argument("--clip", choices=CLIPS, default=None, help="Zuschnitt (Standard: ganz Berlin)")
    return parser


class Pfade:
    """Ein- und Ausgabedateien der Prozessierung für ein Netz und einen Zuschnitt."""

    def __init__(self, netz: str = DEFAULT_NETZ, clip: str | None = None):
        self.netz = netz
        self.clip = clip
        self.clip_suffix = f"_{clip}" if clip else ""
        self.suffix = ("_ren" if netz == "ren" else "") + self.clip_suffix

    def _out(self, name: str, endung: str = "fgb") -> Path:
        return OUTPUT / f"{name}{self.suffix}.{endung}"

    @property
    def snapping_enriched(self) -> Path:
        """Netz mit den Attributen aus dem Matching, vor der Konvertierung (Eingang von start_bikelane_conversion.py)."""
        return self._out("snapping_network_enriched")

    @property
    def datensatz_b(self) -> Path:
        """Datensatz B, Radverkehrsanlagen."""
        return self._out("snapping_converted_bikelanes")

    @property
    def datensatz_c(self) -> Path:
        """Datensatz C, aggregiertes Netz."""
        return self._out("aggregated_rvn_final", "gpkg")

    @property
    def matched_tilda_ways(self) -> Path:
        """TILDA-Wege mit gematchter Länge (Rust-Matching)."""
        return PROCESSING / MATCHING_DIR[self.netz] / f"matched_tilda_ways{self.clip_suffix}.fgb"

    def tilda_routing(self, quelle: str) -> Path:
        """Übersetzte TILDA-Routing-Wege, quelle = bikelanes | streets | paths."""
        return PROCESSING / TILDA_ROUTING_DIR[self.netz] / f"TILDA Routing {quelle.title()} Translated.fgb"

    @property
    def knotenpunkte(self) -> Path:
        """Knotenpunkte, wie sie start_bikelane_conversion.py für die Konvertierung an Kreuzungen liest."""
        return PROCESSING / "data-raw-tilda" / "knotenpunkte_mit_id_und_bezirken.gpkg"

    def analyse(self, name: str) -> Path:
        """Ausgabedatei unter output/analysis/, mit Suffix; legt den Ordner an."""
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        stamm, _, endung = name.rpartition(".")
        return ANALYSIS_DIR / f"{stamm}{self.suffix}.{endung}"
