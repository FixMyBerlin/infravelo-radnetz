## Radinfrastruktur (bikelanes)

- oneway=yes|no
- width (Breite)
  - Vorhandene width-Werte prüfen
  - Runden auf ~10cm
  - TODO TJO: Regeln für Breite erfassen eintragen
- traffic_sign (Verkehrszeichen, Fallback "none")
- surface (Oberfläche)
  - https://wiki.openstreetmap.org/wiki/Tag:surface%3Dsett#Size
    - Mosaik: `surface=sett + sett:length=0.05`
    - Kleinsteinpflaster: `surface=sett + sett:length=0.10`
- surface:colour wenn Farbbeschichtung vorhanden

Für geschützte Radfahrstreifen (PBL)
- separation:left|right (Trennung)
  - https://wiki.openstreetmap.org/wiki/Proposal:Separation#Typical_separation_values
- traffic_mode:right=parking (Verkehrsmodus rechts: Parken)
- traffic_mode:right=foot (Verkehrsmodus rechts: Fußgänger)
- immer buffer:left|right (ggf. buffer=no)
- immer marking:left|right (Markierung)

## Straßen (roads)

- oneway=yes (Einbahnstraße)
  - oneway:bicycle=yes|no setzen
- surface (Oberfläche)
- surface:colour wenn Farbbeschichtung vorhanden


## ERGÄNZEN
- cycleway:note=Erklärung…
- `traffic_sign=Straßenschäden`, `traffic_sign=Gehwegschäden`, `traffic_sign=Radwegschäden`
  - UND `source:traffic_sign:mapillary=ID`

```
