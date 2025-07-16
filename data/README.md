# Data

The checkedin datasets are used to 

The `TILDA Radwege Berlin.fgb` is the export of the TILDA Region, based on OpenStreetMap.
`TILDA Straßen Berlin.fgb` is the export of the street network of TILDA Region, based on OpenStreetMap.
`Berlin Radvorrangsnetz.fgb` is a filtered geodata file of the cycle network of Berlin, which only contains "Radvorrangsnetz" edges.

# Data Modifiers

We use manual maintained lists of OpenStreetMap way ids, which **modify** the final dataset.

`exclude_ways.txt` contains a list of OSM way ids in every line, which should be **removed** from the final dataset.
`include_ways.txt` contains a list of OSM way ids in every line, which should be **added** to the final dataset.

