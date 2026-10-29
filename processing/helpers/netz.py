# -*- coding: utf-8 -*-
"""
netz.py
Auswahl des Zielnetzes der Prozessierung (Parameter --netz).

- rvn: Radvorrangnetz (data/Berlin Radvorrangsnetz.fgb), wie bisher
- ren: REN+, also alle Netzquellen gemeinsam (ren-network/output/ren_netz_gesamt.gpkg)

Beide Netze werden an denselben virtuellen Knotenpunkten geteilt
(data/Virtuelle-Knotenpunkte.gpkg). Alle Pfade sind relativ zu processing/.
"""

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


def datei_zusatz(netz=DEFAULT_NETZ, clip=None):
    """Zusatz der Ausgabedateien von execute_processing.sh: _ren für das REN+, dann _<region>."""
    return ("_ren" if netz == "ren" else "") + (f"_{clip}" if clip else "")


def add_netz_argument(parser):
    """Fügt --netz zu einem argparse-Parser hinzu."""
    parser.add_argument("--netz", choices=NETZE, default=DEFAULT_NETZ,
                        help="Zielnetz: rvn (Radvorrangnetz) oder ren (REN+, alle Netzquellen gemeinsam). Standard: rvn")
