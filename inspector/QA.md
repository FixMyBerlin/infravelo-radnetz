## bikelanes

- oneway=yes|no
- width
  - Vorhandene width Werte prüfen
  - Runden auf ~10cm
  - TODO TJO: Regeln für Breite Erfassen eintragen
- traffic_sign (Fallback "none")
- surface
  - https://wiki.openstreetmap.org/wiki/Tag:surface%3Dsett#Size
    - Mosaik: `surface=sett + sett:length=0.05`
    - Kleinsteinpflaster: `surface=sett + sett:length=0.10`
- surface:colour wenn Farbbeschichtung

For PBL
- separation:left|right
  - https://wiki.openstreetmap.org/wiki/Proposal:Separation#Typical_separation_values
- traffic_mode:right=parking
- traffic_mode:right=foot
- immer buffer:left|right (ggf. buffer=no)
- immer marking:left|right

## roads

- oneway=yes
  - oneway:bicycle=yes|no setzen
- surface
- surface:colour wenn Farbbeschichtung


## ERGÄNZEN
- cycleway:note=Erklärung…
- `traffic_sign=Straßenschäden`, `traffic_sign=Gehwegschäden`, `traffic_sign=Radwegschäden`
  - UND `source:traffic_sign:mapillary=ID`
