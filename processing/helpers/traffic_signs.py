#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
traffic_signs.py
----------------
Hilfsfunktionen für die Verarbeitung von Verkehrszeichen aus OSM-Daten.
"""

import pandas as pd


def has_traffic_sign(traffic_sign_value: str, target_sign: str) -> bool:
    """
    Prüft, ob ein bestimmtes Verkehrszeichen in einem traffic_sign Wert vorhanden ist.
    
    Args:
        traffic_sign_value: Der traffic_sign Wert aus OSM (z.B. "DE:240" oder "DE:1022,240")
        target_sign: Das gesuchte Verkehrszeichen (z.B. "240")
    
    Returns:
        True wenn das Verkehrszeichen mit DE: Präfix gefunden wird
    """
    if not traffic_sign_value or pd.isna(traffic_sign_value):
        return False
    
    traffic_sign_str = str(traffic_sign_value).strip()
    
    # Prüfe auf "DE:XXX" Format (direkter Match)
    if f"DE:{target_sign}" in traffic_sign_str:
        return True
    
    # Prüfe auf "DE:XXX,YYY" Format - teile bei Komma und prüfe jeden Teil
    parts = traffic_sign_str.split(",")
    for part in parts:
        part = part.strip()
        # Wenn der Teil mit "DE:" beginnt, extrahiere die Nummer
        if part.startswith("DE:"):
            sign_number = part[3:]  # Entferne "DE:" Präfix
            if sign_number == target_sign:
                return True
        # Wenn der Teil nur eine Nummer ist und wir bereits ein "DE:" am Anfang hatten
        elif part.isdigit() and "DE:" in traffic_sign_str:
            if part == target_sign:
                return True
    
    return False
