```instructions
---
applyTo: '*/**.py'
---

Verwendet Python, geopandas und andere Bibliotheken zur Verarbeitung von Geodaten und OpenStreetMap-Daten.

# Struktur
Es gibt drei Hauptprozesse und Python-Skripte:
1. Matching (processing/start_matching.py)
2. Snapping (processing/start_snapping.py)
3. Aggregation (processing/start_aggregation.py)

## Snapping-Algorithmus

Dieses Skript befasst sich mit der Herausforderung, OSM (OpenStreetMap)-Attribute präzise auf ein topologisch korrektes, richtungsorientiertes Straßennetz (wie ein Radvorrangsnetz) zu übertragen. Das Ziel ist es, jedem Segment des Zielnetzwerks relevante OSM-Eigenschaften (wie Breite, Oberflächenfarbe, bauliche Trennung, Oberflächentyp, Einbahnstraßenstatus usw.) zuzuweisen.

Die Methodik umfasst zunächst die Aufteilung des Zielnetzwerks in kleine, einheitliche Segmente, um eine präzise Attributzuordnung zu ermöglichen. Für jedes Segment werden geeignete OSM-Ways innerhalb eines räumlichen Puffers identifiziert, und deren Attribute werden übertragen – wobei sowohl die geometrische Nähe als auch die Richtungsübereinstimmung berücksichtigt werden, um genaue Zuordnungen sicherzustellen. Schließlich werden benachbarte Segmente mit identischen Attributen wieder zusammengeführt.

Das Ergebnis ist ein angereichertes Straßennetz, bei dem jedes Segment die relevanten OSM-Attribute trägt.

## Richtungsberechnung (ri-Attribut)

Das `ri`-Attribut (Richtung) ist zentral für das gesamte Datenmodell und wird im Snapping-Prozess berechnet.

**Werte:**
- `ri=0`: Hinrichtung (Kante verläuft in gleicher Richtung wie die Geometrie)
- `ri=1`: Rückrichtung (Kante verläuft entgegengesetzt zur Geometrie)

**Berechnung:**

Die Richtung wird durch Vergleich der Winkel zwischen der Netzwerkkante und dem gematchten TILDA-Weg bestimmt:

1. **Winkelberechnung** (`calculate_line_angle`): Für jede Geometrie wird der Richtungswinkel vom Start- zum Endpunkt berechnet (0-360°)
2. **Richtungsbestimmung** (`determine_segment_direction`): 
   - Berechnet Winkeldifferenz zwischen Segment und OSM-Weg
   - Wenn Winkeldifferenz < 90°: `ri=0` (gleiche Richtung)
   - Wenn Winkeldifferenz ≥ 90°: `ri=1` (entgegengesetzte Richtung)

**Wichtig:**
- Pro Straßensegment (`element_nr`) entstehen normalerweise **zwei Kanten** (ri=0 und ri=1), eine pro Fahrtrichtung
- Ausnahme: Bei Einbahnstraßen gibt es nur eine Kante
- Die Aggregation erfolgt immer nach `element_nr` UND `ri` zusammen

## Chat

- Beim Ausführen von Code in der Konsole nicht vergessen, zuerst die virtuelle Python Umgebung zu konfigurieren/aktivieren
- Wenn es eine Folgeanfrage im Chat gibt, prüfe zunächst, ob der Benutzer Änderungen am Code manuell vorgenommen hat; überschreibe diese Änderungen nicht, sondern integriere sie.
- Füge nützliche und strukturierte Kommentare auf Deutsch zum Code hinzu.
- Strukturiere den Code in sinnvolle Funktionen mit angemessener Funktionsgröße.
- Verwende englische Funktions- und Variablennamen.
- Verwende Logging anstelle von Print-Anweisungen.
- Importiere Pakete nur einmal am Anfang der Datei.
- Verwende wenn möglich die globals.py, um Konstanten wie DEFAULT_CRS oder DEFAULT_OUTPUT_DIR zu importieren.
- Verwende wenn möglich Helpers aus dem helpers-Ordner.
- Füge neue Helpers, wenn sie in verschiedenen Modulen verwendet werden können, dem helpers-Ordner hinzu.
- Entferne ungenutzte Imports.
- Wenn es viele verschiedene Möglichkeiten in der Methode oder Implementierung gibt, frage zuerst nach den Präferenzen des Benutzers.
- Aktualisiere die requirements.txt-Datei mit den neuen Paketen, die im Code verwendet werden.
- Jedes Python-Modul sollte alle relevanten Eingabe- und Ausgabedateien im Docstring am Anfang der Datei enthalten.
- Stelle beim Testen der Skripte sicher, dass die Skripte mit dem neukoelln-CLI-Parameter ausgeführt werden, damit die Ausführung schneller ist.
- Beachte, dass es immer MultiLineString-Geometrieobjekte gibt, nicht nur LineString.
- Entferne gecachte Dateien, bevor du Python-Skripte ausführst.
- Beachte, dass es zwei Richtungen für jede Kante in Snapping- und aggregierten Geodaten gibt!

```
