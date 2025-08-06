# Testing Framework für infraVelo Radnetz

Dieses Verzeichnis enthält automatisierte Qualitätssicherungstests.

## Dateien

- `test_final_results.py` - Hauptskript für die Test-Durchführung
- `test_cases.json` - Test-Definitionen und erwartete Werte

## Verwendung

### Einzelne Test-Ausführung
```bash
# Teste Berlin-weite Ergebnisse
python testing/test_final_results.py

# Teste Neukölln-Ergebnisse  
python testing/test_final_results.py --clip-neukoelln
```

### Integration in execute_processing.sh
Die Tests werden automatisch am Ende der Verarbeitung ausgeführt.

## Test-Definitionen

### Aggregated Tests
Testen die finalen aggregierten Ergebnisse in `output/aggregated_rvn_final[_neukoelln].gpkg`

### Snapping Tests
Testen die Snapping-Ergebnisse in `output/snapping_network_enriched[_neukoelln].fgb`

**Test-Modi für Snapping:**
- `any_segment`: Mindestens ein Segment der element_nr muss alle Attribute haben

## Test-Cases erweitern

Neue Test-Cases können in `test_cases.json` hinzugefügt werden:

```json
{
  "snapping_tests": [
    {
      "name": "Mein neuer Test",
      "element_nr": "12345_67890.01", 
      "expected_attributes": {
        "strassenname": "Beispielstraße",
        "fuehr": "Radweg",
        "pflicht": true
      },
      "test_mode": "any_segment",
      "geometry_requirements": {
        "min_length_meters": 15.0
      }
    }
  ]
}
```

## Attribut-Validierung

- **NULL-Werte**: Tests schlagen fehl wenn Attribute NULL/None sind
- **Datentypen**: Automatische Konvertierung für bool/int/float
- **Strings**: Exakte Übereinstimmung erforderlich

## Geometrie-Validierung

- **min_length_meters**: Mindestlänge des Segments in Metern
- Weitere Geometrie-Anforderungen können hinzugefügt werden (max_length, min_area, etc.)

## Ausgabe

Das Skript gibt einen detaillierten Bericht aus und verwendet Exit Codes:
- `0`: Alle Tests erfolgreich
- `1`: Mindestens ein Test fehlgeschlagen
