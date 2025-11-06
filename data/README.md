# Data

Bei den eingecheckten Dateien handelt es sich um:

`TILDA Radwege Berlin.fgb` Export von Radwegen in TILDA, basierend auf OpenStreetMap.
`TILDA Straßen Berlin.fgb` Export von Straßen in TILDA, basierend auf OpenStreetMap.
`TILDA Wege Berlin.fgb` Export von Straßen in TILDA, basierend auf OpenStreetMap.
`Berlin Radvorrangsnetz.fgb` gefilterte Geodaten basierend auf dem Radnetz Berlin, welches nur „Radvorrangsnetz“ Kanten enthält.

Für Lizenzen, siehe [LIZENZEN.md](./LIZENZEN.md)

# Data Modifiers

Wir verwenden manuell gepflegte Listen von OpenStreetMap-Way-IDs, die das endgültige Datenset verändern.

`exclude_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die aus dem finalen Datensatz **entfernt** werden soll.
`include_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die dem finalen Datensatz **hinzugefügt** werden soll.
`opposite_edge_overwrite_element_nr.txt` enthält in jeder Zeile eine `element_nr`, für die die entgegengesetzte Richtung (ri=1) aus dem finalen Datensatz **entfernt** werden soll. Das ist nützlich, wenn der Snapping-Prozess fälschlicherweise Infrastruktur in beide Richtungen zuordnet, in der Realität aber nur die Vorwärtsrichtung (ri=0) existiert.

