#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py
------------------------------------------------------
Initiales Setup-Skript für das Projekt.
Erstellt die benötigten QA-Ordner für Ausgaben.
"""
import os

# Zu erstellende Ordner
folders = [
    os.path.join("..", "output", "qa-snapping"),
    os.path.join("..", "output", "qa-matching"),
]

def main():
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
        print(f"✔ Ordner erstellt (falls nicht vorhanden): {folder}")

if __name__ == "__main__":
    main()
