# -*- coding: utf-8 -*-
"""
netz.py
Auswahl des Zielnetzes der Prozessierung (Parameter --netz).

- rvn: Radvorrangnetz (data/Berlin Radvorrangsnetz.fgb), wie bisher
- ren: REN+, also alle Netzquellen gemeinsam (ren-network/output/ren_netz_gesamt.gpkg).
  Mit den Korrekturen aus der App Netzanpassungen (ren-network/import_app_export.py) liegt daneben
  ren_netz_gesamt_korrigiert.gpkg. Das Matching rechnet standardmäßig mit dem korrigierten Netz,
  solange die Datei existiert (--quelle, siehe waehle_quelle).

Beide Netze werden an denselben virtuellen Knotenpunkten geteilt
(data/Virtuelle-Knotenpunkte.gpkg). Alle Pfade sind relativ zu processing/.
"""

import logging
from pathlib import Path

NETZE = ("rvn", "ren")
DEFAULT_NETZ = "rvn"

# Eingangsnetz und Zwischendateien von process_radnetz.sh je Netz
PFADE = {
    "rvn": {
        "quelle": "data/Berlin Radvorrangsnetz.fgb",
        "quelle_layer": None,
        "geteilt": "output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb",
        "detailnetz_geteilt": "output/rvn/Berlin Detailnetz_mit_virtuellen-knotenpunkten.fgb",
        "mit_element_nr": "output/rvn/Berlin Vorrangnetz_with_element_nr.fgb",
        "kombiniert": "output/rvn/vorrangnetz_details_combined_rvn.fgb",
    },
    "ren": {
        "quelle": "../ren-network/output/ren_netz_gesamt.gpkg",
        "quelle_layer": "ren_netz",
        "quelle_korrigiert": "../ren-network/output/ren_netz_gesamt_korrigiert.gpkg",
        "geteilt": "output/ren/ren_netz_mit_virtuellen-knotenpunkten.fgb",
        "detailnetz_geteilt": "output/ren/Berlin Detailnetz_mit_virtuellen-knotenpunkten.fgb",
        "mit_element_nr": "output/ren/ren_netz_with_element_nr.fgb",
        "kombiniert": "output/ren/ren_netz_details_combined.fgb",
    },
}

# TILDA-Routing je Netz (prepare_tilda_routing.py). Für das REN+ ohne Zuschnitt auf den RVN-Puffer.
# Die Rust-Konfiguration (map-matching/config/default.toml, [netze.*]) liest dieselben Ordner.
TILDA_ROUTING_DIR = {
    "rvn": "output/TILDA-routing",
    "ren": "output/TILDA-routing-ren",
}

# Ausgabeordner des Rust-Matchings je Netz (map-matching/config/default.toml, [netze.*])
MATCHING_DIR = {
    "rvn": "output/map-matching",
    "ren": "output/map-matching-ren",
}


# Welche Quelle das REN+ liefert: korrigiert, falls vorhanden (auto), oder erzwungen
QUELLE_WAHL = ("auto", "korrigiert", "original")
DEFAULT_QUELLE = "auto"


def waehle_quelle(netz=DEFAULT_NETZ, wahl=DEFAULT_QUELLE):
    """Eingangsnetz der Prozessierung: (Pfad, korrigiert). Nur das REN+ hat eine korrigierte Fassung.

    auto: ren_netz_gesamt_korrigiert.gpkg, wenn die Datei existiert, sonst das Original.
    korrigiert: wie auto, bricht aber ab, wenn die Datei fehlt.
    original: immer ren_netz_gesamt.gpkg (der Stand, den der Kunde bekommt).
    """
    pfade = PFADE[netz]
    korrigiert_pfad = pfade.get("quelle_korrigiert")
    if korrigiert_pfad is None:
        if wahl == "korrigiert":
            raise SystemExit(f"Für das Netz {netz} gibt es keine korrigierte Fassung (nur ren).")
        return pfade["quelle"], False
    vorhanden = Path(korrigiert_pfad).exists()
    if wahl == "korrigiert" and not vorhanden:
        raise SystemExit(f"{korrigiert_pfad} fehlt. Zuerst python netzanpassungen/import_app_export.py ausführen "
                         f"oder --quelle original wählen.")
    if wahl != "original" and vorhanden:
        logging.info(f"Eingangsnetz: korrigiertes REN+ ({korrigiert_pfad})")
        return korrigiert_pfad, True
    grund = "auf Wunsch (--quelle original)" if wahl == "original" else "keine korrigierte Fassung vorhanden"
    logging.info(f"Eingangsnetz: Original-REN+ ({pfade['quelle']}), {grund}")
    return pfade["quelle"], False


def datei_zusatz(netz=DEFAULT_NETZ, clip=None):
    """Zusatz der Ausgabedateien von execute_processing.sh: _ren für das REN+, dann _<region>."""
    return ("_ren" if netz == "ren" else "") + (f"_{clip}" if clip else "")


def add_quelle_argument(parser):
    """Fügt --quelle zu einem argparse-Parser hinzu."""
    parser.add_argument("--quelle", choices=QUELLE_WAHL, default=DEFAULT_QUELLE,
                        help="REN+-Eingangsnetz: korrigiert (aus der App Netzanpassungen) oder original. "
                             "Standard auto: korrigiert, wenn ren_netz_gesamt_korrigiert.gpkg existiert")


def add_netz_argument(parser):
    """Fügt --netz zu einem argparse-Parser hinzu."""
    parser.add_argument("--netz", choices=NETZE, default=DEFAULT_NETZ,
                        help="Zielnetz: rvn (Radvorrangnetz) oder ren (REN+, alle Netzquellen gemeinsam). Standard: rvn")
