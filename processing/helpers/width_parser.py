#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
width_parser.py
---------------
Hilfsfunktionen zur Vereinheitlichung von OSM-Breitenangaben.
"""

import pandas as pd


def parse_width(width_value) -> float:
    """
    Wandelt OSM-Breitenangaben in standardisierte Meter-Werte um.
    Rundet auf 0,10 m-Stellen und gibt das Ergebnis als Float zurück.
    
    Args:
        width_value: OSM width-Wert (kann String oder Number sein)
    
    Returns:
        Breite in Metern gerundet auf 0,10 m, oder None wenn nicht parsbar
    """
    if not width_value or pd.isna(width_value):
        return None
        
    try:
        # String zu Float konvertieren, falls nötig
        if isinstance(width_value, str):
            # Entferne Einheiten und andere Zeichen
            width_str = str(width_value).strip().lower()
            # Entferne "m", "meter", "metres" etc.
            width_str = width_str.replace("m", "").replace("eter", "").replace("tres", "")
            # Entferne Leerzeichen
            width_str = width_str.strip()
            # Falls mehrere Werte durch Semikolon getrennt sind, nehme den ersten
            if ";" in width_str:
                width_str = width_str.split(";")[0].strip()
            width_float = float(width_str)
        else:
            width_float = float(width_value)
        
        # Auf 0,10 m runden (d.h. auf eine Dezimalstelle)
        return round(width_float, 1)
        
    except (ValueError, TypeError):
        return None
