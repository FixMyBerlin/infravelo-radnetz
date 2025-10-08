# Data

Bei den eingecheckten Dateien handelt es sich um:

`TILDA Radwege Berlin.fgb` Export von Radwegen in TILDA, basierend auf OpenStreetMap.
`TILDA Straßen Berlin.fgb` Export von Straßen in TILDA, basierend auf OpenStreetMap.
`TILDA Wege Berlin.fgb` Export von Straßen in TILDA, basierend auf OpenStreetMap.
`Berlin Radvorrangsnetz.fgb` gefilterte Geodaten basierend auf dem Radnetz Berlin, welches nur „Radvorrangsnetz“ Kanten enthält.

Für Lizenzen, siehe LIZENZEN.md

# Data Modifiers

We use manual maintained lists of OpenStreetMap way ids, which **modify** the final dataset.

`exclude_ways.txt` contains a list of OSM way ids in every line, which should be **removed** from the final dataset.
`include_ways.txt` contains a list of OSM way ids in every line, which should be **added** to the final dataset.
`opposite_edge_overwrite_element_nr.txt` contains a list of element_nr in every line, where the opposite direction (ri=1) should be **removed** from the final dataset. This is useful when the snapping process incorrectly assigns infrastructure to both directions, but only the forward direction (ri=0) actually exists.

