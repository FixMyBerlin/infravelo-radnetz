# Anforderungen für die Properties

## Attribute, die von der Kante übertragen werden

Siehe https://docs.google.com/spreadsheets/d/1GjvJZkBGIGyeYdw9z1yKYb7YLZZsugQgkQmAKlVwc_E/edit?gid=0#gid=0
- `elem_nr`
- `vonNK`
- `bisNK`
- `laenge`
- `ri` (Richtung)
- `bez_nr` (Bezirksnummer)
- `str_name`

## Attribute, die von TILDA Daten übertragen werden

### `verkehrsri` (Verkehrsrichtung (Radverkehr))

**Werte:**
- `Einrichtungsverkehr`
- `Zweirichtungsverkehr`

**Definition**
- Datensatz: `bikelanes`:
  - `oneway=yes` => Einrichtungsverkehr
  - `oneway=no` => Zweirichtungsverkehr
  - `oneway=car_not_bike` => Zweirichtungsverkehr
  - `oneway=assumed_no` => (QA)
  - `oneway=implicit_yes` => (QA)

- Datensatz: `roads` und Datensatz: `paths`:
  - `oneway=nil` => Zweirichtungsverkehr
  - `oneway=yes` => Einrichtungsverkehr
  - `oneway=yes_dual_carriageway` => Einrichtungsverkehr
  - `oneway=no` => Zweirichtungsverkehr
  - `oneway_bicycle=no` => Zweirichtungsverkehr


### `fuehr` (Art der Radverkehrsführung)

**Werte + Definition:**

- `Radfahrstreifen`
  - => bikelanes: `category=cyclewayOnHighway_exclusive`
- `Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)`
  - => bikelanes: `category=sharedBusLaneBikeWithBus`
  - QA-Story: Validate traffic_signs for this category
- `Geschützter Radfahrstreifen`
  - => bikelanes: `category=cyclewayOnHighwayProtected`
- `Schutzstreifen`
  - => bikelanes: `category=cyclewayOnHighway_advisory`
- `Fahrradstraße /-zone (Z 244)`
  - => bikelanes: `category=bicycleRoad,  bicycleRoad_vehicleDestination"` (OR)
- `Radweg`
  - => bikelanes: `category=footAndCyclewayShared_*,  footAndCyclewaySegregated_*,  cycleway_adjoining, cyclewaySeparated_*` (OR LIKE)
- `Gemeinsamer Geh- und Radweg mit Z240`
  - => bikelanes: `category="footAndCyclewayShared_* + traffic_sign INCLUDES 240` (AND)
- `Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022-10)`
  - => bikelanes: `category=sharedBusLaneBusWithBike`
  - QA-Story: Validate traffic_signs for this category
- `Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)`
  - => bikelanes: `category=footwayBicycleYes + traffic_sign INCLUDES 239 + traffic_sign INCLUDES 1022-10` (AND)
- `Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)`
  - => bikelanes: `category=pedestrianAreaBicycleYes + traffic_sign INCLUDES 242 + traffic_sign INCLUDES 1022-10` (AND)
- `Mischverkehr mit motorisiertem Verkehr`
  - => roads
- `Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)`
  - => roadsPathClasses

- `[TODO]Klärung notwendig`
  - => bikelanes: `category=needsClarification`

### `pflicht` (Benutzungspflicht der RVA)

**Werte + Definition:**

> Vorliegen einer Benutzungspflicht der RVA (Z237, 240, 241)

Vorgehen im Detail TBD. Wir starten mal mit dieser einfachen Lösung. Es könnte aber sein, dass wir für bestimmte fuehr-Werte stattdessen das Feld leer lassen.

- `Ja`
  - => bikelanes: `traffic_sign INCLUDES 237, 240, 241`
- `Nein`
  - => bikelanes: `traffic_sign DOES NOT INLCUDE 237, 240, 241`
  - => roads*: immer "Nein"

### `ofm` (Oberflächenmaterial der RVA)

**Werte + Definition:**

- "Asphalt"
  - => `surface=asphalt`
- "Beton (Platte etc.)"
  - => `surface='concrete', 'concrete:plates', 'concrete:lanes',`
- "Gepflastert (Berliner Platte, Mosaik, Kleinstein...)"
  - => `surface=paving_stones OR mosaic_sett OR small_sett OR large_sett`
- "Kopfsteinpflaster / Großstein"
  - => `surface=sett OR cobblestone OR bricks OR stone`
- "Ungebunden"
  - => `surface='unpaved', 'ground', 'grass', 'sand', 'compacted', 'fine_gravel', 'gravel',`

NOTE: Andere Begriffe loggen lassen.
In processing/topics/helper/sanitize_tags.lua haben wir noch andere Begriffe, die ggf. vorkommen können.
Wir müssen das entweder nochmal abgleichen, oder loggen wenn neue Begriffe vorkommen.

### `farbe` (Durchgehende farbliche Beschichtung)

- "Ja"
  - => `surface_color=red OR green` (OR)
- "Nein"
  - Rest

### `protek` (Art der physischen Protektion)

Ist nur bei `Geschützter Radfahrstreifen` (`category=protectedCyclewayOnHighway`) relevant.

- "Poller (auf Sperrfläche)"
  => `separation:left=bollard + buffer:left=1 (inkl. Linien) + marking:left=barred_area`
    KLÄREN: Was ist, wenn es nicht die Sperrfläche ist? Also bspw. durchgezogene Linie.
    KLÄREN: Was tun bei Poller mit Linie, Poller zwischen zwei Linien
- "Schwellen (auf Sperrfläche)"
  => `separation*=bump`
    SIEHE OBEN
- "Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)"
  => `separation*=vertical_panel + buffer:left=no`
    `buffer:left=no|0`
    Hinweis: Wir prüfen nicht explizit den Breitstrich
- "Ruhender Verkehr (mit Sperrfläche)"
  => `traffic_mode:left=parking + marking:left=barred_area`
    KLÄREN: Was wenn nur Linie
    HINWEIS: Wenn Poller als Trennung zwischen ruhendem Verkehr und greifen die Poller
      `separation:left=poller + traffc_mode:left=parking`
- "Sonstige (z.B. Pflanzkübel, Leitplanke)"
  => `separation*=planter,guard_rail, TODO`
    KLÄREN: Poller ohne Sperrfläche hier rein?
- "nur Sperrfläche"
  => `markings:left=barred_area + separation:left=no + buffer:left=ZAHL`
    KLÄREN: Doppelte Linien als Sperrfläche oder Sonstiges verstehen? Analog "Ruhender Verkehr (mit Sperrfläche)"
- "Ohne"
  => `separation:left=no|nil`


### `trennstreifen` (Sicherheitstrennstreifen bei rechtsseitig ruhendem Verkehr)

>Das Vorhandensein eines Sicherheitstrennstreifens zum in Fahrtrichtung rechtsseitigen ruhenden Verkehr ist zu erfassen. Vergleiche hierzu die Regelpläne 311 und 312.

   > **❗ Achtung:** Hier muss noch die Betrachtung von Fahrradstraßen rein, da diese beidseitig einen Trennstreifen benötigen.

- "Ja"
  - Wenn `traffic_mode:right=parking + marking:right=dashed_line|solid_line + (cycleway:right:)buffer:right=0.6`
- "Nein"
  - Rest
  - "Es wird darauf hingewiesen, dass Sicherheitstrennstreifen im Regelfall nur bei Schutzstreifen, Radfahrstreifen und Fahrradstraßen auftreten. 	"
- "entfällt"
  - …(kein rechtsseitig ruhender Verkehr) 
  - Das Attribut ist immer zu erheben, wenn kein rechtsseitig ruhender Verkehr vorliegt, ist „entfällt“ anzugeben. 

### `nutz_beschr` (Nutzungsbeschränkung aufgrund baulicher Mängel)

> Ziel ist die Erhebung von angezeigten Nutzungsbeschränkungen von RVA. Es soll hierbei unterschieden werden, ob eine bestehende Radverkehrsinfrastruktur physisch für die Nutzung gesperrt ist (beispielsweise durch eine Absperrschranke (Z 600)), ob die Nutzung eingeschränkt ist (beispielsweise ein Zusatzzeichen „Radwegschäden“), oder ob keine Beeinträchtigung vorliegt. 
> Es wird davon ausgegangen, dass diese Nutzungsbeschränkung meist zu Beginn einer Kante vorliegt. In Einzelfällen kann dies aber auch innerhalb einer Kante geschehen. 

- "Physische Sperre (Absperrschranke (Z600) oder sonstige Zufahrtssperre (z.B. Poller)) "
  - TODO: Orte gesondert vermerken
- "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden) "
  - `traffic_sign=Straßenschäden`, `traffic_sign=Gehwegschäden`, `traffic_sign=Radwegschäden`
  - UND `source:traffic_sign:mapillary=ID`
- "keine"

### `Bemerkung`

- Wenn temporary=yes => Bemerkung "Weg als temporärer Weg eingetragen; vermutlich Baustellen-Weg"
- OSM-Description mit übernehmen(?) Aber da sind ein paar Hinweise drin, die nicht so relevant sind für diesen Datensatz. Sollten wir also ggf. mit einem Prefix versehen.
