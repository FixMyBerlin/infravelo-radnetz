# Analysen

Auswertungen der Prozessierungsergebnisse. Anders als die [Validierung](../validation/README.md) prüfen sie keine Regeln und haben keinen Exit-Code für bestanden/nicht bestanden. Sie zählen, schlüsseln auf oder exportieren Auffälligkeiten zum Ansehen in QGIS.

## Aufruf

Aus `processing/`:

```bash
../.venv/bin/python analysis/analyze_null_width.py                 # REN+, ganz Berlin
../.venv/bin/python analysis/analyze_null_width.py --netz rvn --clip neukoelln
```

Alle Skripte außer `analyse_verteilung_ren.py` nehmen `--netz ren|rvn` (Standard `ren`, wie die Pipeline) und `--clip neukoelln|norden|sueden`. Sie lesen dann die Dateien mit demselben Suffix, die `execute_processing.sh` schreibt, z. B. `output/snapping_network_enriched_ren.fgb`. Dateiausgaben landen in `output/analysis/`, ebenfalls mit Suffix.

## Skripte

| Skript | Liest | Ergebnis |
|---|---|---|
| `analyze_null_attributes.py` | Netz mit Attributen, Datensatz B, Datensatz C | NULL-Werte je Attribut (Terminal) |
| `analyze_null_width.py` | Netz mit Attributen | `breite` = NULL je Führungsform, Ausnahme wie in der Validierung nur Mischverkehr (Terminal) |
| `analyze_todo_attributes.py` | Netz mit Attributen | TODO-Werte je Führungsform und Attribut (Terminal) |
| `analyze_missing_widths.py` | Netz mit Attributen, `matched_tilda_ways` | TILDA-Wege der Radinfrastruktur ohne Breite (`tilda_missing_widths.geojson`) |
| `analyse_dual_carriageway.py` | TILDA-Straßen, Netz mit Attributen | Einbahnstraßen, denen in OSM vermutlich `dual_carriageway=yes` fehlt (`potential_missing_dual_carriageway.fgb`) |
| `analyse_kreuzungswege_auf_strecke.py` | Datensatz B, Knotenpunkte (Abgabestand), TILDA-Straßen | Kreuzungswege (auch konvertierte) weiter als `--abstand` (Standard 25 m) vom nächsten Knotenpunkt, z. B. Verschwenkungen; Spalte `quert_nebenstrasse`, wenn eine benannte Straße außerhalb des Netzes gequert wird (`kreuzungswege_auf_strecke.fgb`) |
| `analyze_schutzstreifen_at_intersections.py` | Netz mit Attributen, Knotenpunkte | Abdeckung von Schutzstreifen an Knotenpunkten je Radius und Überlappung (Terminal) |
| `debug_segment_conversion.py` | Netz mit Attributen, Knotenpunkte | Schritte der Konvertierung zu „Kreuzungsweg (Konvertiert)“ für ein Segment (`sfid` als Argument) |
| `analyse_verteilung_ren.py` | REN+, TILDA-Routing | Verteilung der Führungsformen auf dem REN+ (ohne RVN); eigenes `--netz kartierung\|ohne-vorrangnetz`, rechnet das Matching selbst |

„Netz mit Attributen“ ist `output/snapping_network_enriched{suffix}.fgb`, das Netz mit den Attributen aus dem Matching vor der Konvertierung in `start_bikelane_conversion.py`.

## Neue Analyse anlegen

```python
#!/usr/bin/env python3
"""Was die Analyse auswertet. Aufruf aus processing/: ../.venv/bin/python analysis/<name>.py"""
import geopandas as gpd

from pfade import Pfade, argumente


def main():
    args = argumente("Was die Analyse auswertet").parse_args()
    p = Pfade(args.netz, args.clip)
    gdf = gpd.read_file(p.datensatz_b)
    ...
    gdf.to_file(p.analyse("ergebnis.fgb"), driver="FlatGeobuf")


if __name__ == "__main__":
    main()
```

[`pfade.py`](pfade.py) kennt die Ausgaben der Pipeline (`snapping_enriched`, `datensatz_b`, `datensatz_c`, `matched_tilda_ways`, `tilda_routing(quelle)`, `knotenpunkte`, `knotenpunkte_abgabe`) und legt `processing/` in den Importpfad, sodass `helpers.…` und `validation.…` importierbar sind. Regeln, die schon die Validierung kennt, von dort importieren statt sie zu kopieren (z. B. `from validation.checks.attribute import MISCHVERKEHR`).

Soll aus einer Analyse eine dauerhafte Regel werden, gehört sie als Prüfung in die Validierung.
