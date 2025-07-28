# Data

Bei den eingecheckten Dateien handelt es sich um:

`TILDA Radwege Berlin.fgb` Export von Radwegen in TILDA, basierend auf OpenStreetMap.
`TILDA Straßen Berlin.fgb` Export von Straßen in TILDA, basierend auf OpenStreetMap.
`Berlin Radvorrangsnetz.fgb` gefilterte Geodaten basierend auf dem Radnetz Berlin, welches nur „Radvorrangsnetz“ Kanten enthält.

Für Lizenzen, siehe LIZENZEN.md

# Data Modifiers

We use manual maintained lists of OpenStreetMap way ids, which **modify** the final dataset.

`exclude_ways.txt` contains a list of OSM way ids in every line, which should be **removed** from the final dataset.
`include_ways.txt` contains a list of OSM way ids in every line, which should be **added** to the final dataset.

