# -*- coding: utf-8 -*-
"""
progressbar.py
Hilfsfunktion für einen Fortschrittsbalken im Terminal.
"""

import time
import shutil

def print_progressbar(current, total, prefix="", length=40, start_time=None):
    """
    Gibt einen Fortschrittsbalken im Terminal aus.
    current: aktueller Fortschritt (int)
    total: Gesamtanzahl (int)
    prefix: Optionaler Text vor dem Balken
    length: Länge des Balkens in Zeichen
    start_time: Optionale Startzeit (time.time()) für ETA-Berechnung
    """
    
    percent = current / total if total else 0
    filled = int(length * percent)
    bar = '\u2588' * filled + '-' * (length - filled)
    
    # Berechne ETA wenn start_time gegeben ist
    eta_str = ""
    if start_time is not None and current > 0:
        elapsed = time.time() - start_time
        rate = current / elapsed if elapsed > 0 else 0
        if rate > 0:
            remaining_items = total - current
            eta_seconds = remaining_items / rate
            if eta_seconds < 60:
                eta_str = f", ETA: {eta_seconds:.0f}s"
            elif eta_seconds < 3600:
                eta_minutes = eta_seconds / 60
                eta_str = f", ETA: {eta_minutes:.1f}min"
            else:
                eta_hours = eta_seconds / 3600
                eta_str = f", ETA: {eta_hours:.1f}h"
    
    # Erstelle die Ausgabezeile
    line = f"\r{prefix}[{bar}] {current}/{total} ({percent:.0%}){eta_str}"
    
    # Ermittle Terminal-Breite und fülle mit Leerzeichen auf, um alte Zeichen zu überschreiben
    try:
        terminal_width = shutil.get_terminal_size().columns
        # Füge Leerzeichen hinzu, um die gesamte vorherige Zeile zu überschreiben
        line = line.ljust(terminal_width)
    except:
        # Fallback: Füge einfach einige Leerzeichen hinzu
        line = line + " " * 20
    
    print(line, end='', flush=True)
    if current == total:
        print()
