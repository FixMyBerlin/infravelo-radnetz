#!/bin/bash
# -*- coding: utf-8 -*-
# run_validation.sh
# ----------------------------------------------------------------
# Validierung der Abgabedatensätze (validation/, siehe validation/README.md).
# Unabhängig von der Prozessierung ausführbar: liest nur die fertigen Dateien.
# Jeder Lauf wird unter validation/runs/ gespeichert und lässt sich mit jedem
# anderen Lauf vergleichen.
#
# Verwendung:
#   ./run_validation.sh [--netz ren|rvn] [--clip neukoelln|norden|sueden] [--output-dir DIR] [--nur B- K-]
#   ./run_validation.sh list                 # gespeicherte Läufe
#   ./run_validation.sh diff                 # zwei Läufe vergleichen (fragt interaktiv)
#   ./run_validation.sh diff 3 7 [--check B-NULL]
#   ./run_validation.sh history              # Anzahl Verstöße je Prüfung über die letzten Läufe
#   ./run_validation.sh show [LAUF]
#
# Exit-Codes:
#   0 - alle Prüfungen mit Schwere „fehler“ bestanden (Warnungen erlaubt)
#   1 - mindestens eine Prüfung fehlgeschlagen oder nicht gelaufen

cd "$(dirname "$0")"
VENV="$(cd .. && pwd)/.venv"
if [ -x "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
else
    PYTHON="python3"
fi

exec "$PYTHON" -m validation "$@"
