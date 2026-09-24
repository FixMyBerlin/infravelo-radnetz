# Legacy: bisheriges Matching & Snapping (nicht mehr verwendet)

Diese Skripte wurden durch das HMM-/Viterbi-Map-Matching in [`map-matching/`](../map-matching/) ersetzt
und werden von `execute_processing.sh` nicht mehr aufgerufen. Sie bleiben nur zum Nachschlagen erhalten.

- `processing/start_matching.py`: buffer-basierte Auswahl der TILDA-Wege mit manuellen Include-/Exclude-Listen
- `processing/start_snapping.py`: Zerlegung in 2,5-m-Segmente mit lokalem Prioritäten-Scoring
- `processing/matching/`, `processing/helpers/snapping_calculations.py`: zugehörige Hilfsmodule

Die Imports (`helpers.*`) setzen voraus, dass `processing/` im `PYTHONPATH` liegt.
