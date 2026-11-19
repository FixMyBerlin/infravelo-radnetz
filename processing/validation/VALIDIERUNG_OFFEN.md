# Validierung: noch einzuführen

Merkzettel für neue Prüfungen. Sie ergänzen die bestehenden Prüfungen in `run_validation.sh` und vereinheitlichen sie. Datensätze: **A** = TILDA-Wege, **B** = `snapping_converted_bikelanes`, **C** = `aggregated_rvn_final`, **K** = Knotenpunkte.

## 1. Neue Prüfungen

### Topologie und Nummern

| Prüfung | Datensatz | Regel |
|---|---|---|
| Zwei Knotenpunkte je Kante | B, C | Jede Kante hat an beiden Enden einen Knotenpunkt. Keine Kante mit nur einem oder gar keinem. |
| Beide Richtungen vorhanden | C | Zu jeder Kante gibt es genau eine Kante mit `ri=0` und eine mit `ri=1`. |
| `element_nr` eindeutig | C | Jede `element_nr` kommt je Richtung nur einmal vor. |
| Virtuelle Knotenpunkte einheitlich | K, B, C | Alle virtuellen Knotenpunkte folgen einem einheitlichen Muster, das noch festzulegen ist (z. B. Präfix `V`, Stellenzahl). |
| Virtuelle Knotenpunkte teilen Kanten | K, B, C | Jeder virtuelle Knotenpunkt muss mindestens eine Kante teilen, also Start- oder Endpunkt von mindestens einer Kante sein, die dadurch entstanden ist. Ein virtueller Knotenpunkt ohne Auswirkung auf eine Kante deutet auf einen Fehler hin (z. B. verwaister Knoten oder Teilung, die nicht stattgefunden hat). |

### Attribute und Inhalte

| Prüfung | Datensatz | Regel |
|---|---|---|
| Nur Werte aus der Leistungsbeschreibung | B, C, K | Jedes Attribut darf nur die dort definierten Werte haben. Die Wertelisten kommen aus der Leistungsbeschreibung und werden als Konfigurationsdatei abgelegt, nicht im Code. |
| Fahrradstraße höchstens 8 m breit | B, C | `fuehr` = Fahrradstraße und `breite` > 8 → Fehler. |
| Keine Kreuzungswege | C | Weder „Kreuzungsweg" noch „Kreuzungsweg (Konvertiert)" in `fuehr`. |
| Knotenpunkte ohne NULL | K | Kein Attribut darf NULL sein. Ist nichts zu erfassen, steht dort „keins". |

### Koordinaten

| Prüfung | Datensatz | Regel |
|---|---|---|
| CRS | alle | EPSG:25833 (ETRS89 / UTM 33N). |
| Rechtswert | alle | 6-stellig, ohne Zonenkennung 33. Im Berliner Gebiet liegt er in EPSG:25833 bei etwa 370 000 bis 415 000. Eine Zahl mit vorangestellter 33 ist ein Fehler. |

Offen: Das GeoJSON-Format ist WGS84. Zu klären ist, ob die Koordinatenprüfung nur die abgegebenen Dateien in EPSG:25833 betrifft.

## 2. Test-Framework

Umgesetzt, siehe [README.md](README.md). Die bisherigen Skripte (`validate_datensatz_b.py`, `validate_datensatz_c.py`, `validate_knotenpunkte.py`, `validate_virtuelle_knotenpunkte.py`, `analyze_check_duplicate_ways.py`) sind in `checks/` überführt. Neue Prüfungen kommen als Funktion mit `@pruefung` dazu.

## 3. Reihenfolge (Vorschlag)
1. ~~Framework-Gerüst mit Übersicht und Detailausgabe, danach die bestehenden Prüfungen überführen.~~ Erledigt.
2. Prüfungen ohne externe Vorgaben: Kanten und Knotenpunkte, beide Richtungen, `element_nr`, Fahrradstraße, Kreuzungswege, Knotenpunkte ohne NULL, Koordinaten.
3. Muster der virtuellen Knotenpunkte festlegen und prüfen, dazu die Prüfung, dass jeder virtuelle Knotenpunkt eine Kante teilt.
4. Wertelisten aus der Leistungsbeschreibung, sobald sie vorliegt.
