# -*- coding: utf-8 -*-
"""
progressbar.py
Hilfsfunktion für einen Fortschrittsbalken im Terminal.
"""
def print_progressbar(current, total, prefix="", length=40):
    """
    Gibt einen Fortschrittsbalken im Terminal aus.
    current: aktueller Fortschritt (int)
    total: Gesamtanzahl (int)
    prefix: Optionaler Text vor dem Balken
    length: Länge des Balkens in Zeichen
    """
    percent = current / total if total else 0
    filled = int(length * percent)
    bar = '\u2588' * filled + '-' * (length - filled)
    print(f"\r{prefix}[{bar}] {current}/{total} ({percent:.0%})", end='', flush=True)
    if current == total:
        print()
