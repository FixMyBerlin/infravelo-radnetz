# Eingeschränkte Wege im TILDA-Routing (Konzept)

Stand: 07.11.2026. Umgesetzt in [FixMyBerlin/tilda-geo-private#39](https://github.com/FixMyBerlin/tilda-geo-private/pull/39); der PR-Text ist die aktuelle Beschreibung. Abweichung vom ursprünglichen Konzept: kein Bbox-Gate, keine leichten Zeilen, Stufe `way` steht nirgends (Infravelo braucht sie nicht). Ergänzt [tilda-routing.md](./tilda-routing.md).

## 1. Anlass

Das TILDA-Routing (`routing`) lässt Wege weg, auf denen Radfahren nicht allgemein erlaubt ist. Das ist für die öffentlichen Daten richtig. Das RVN führt aber teilweise über solche Wege, und das Ergebnis 2025 hat sie benutzt.

Wie geprüft: Alle Wege aus `ergebnis_2025_datensatz_c` (`tilda_id`, `tilda_ids`), aktuelle OSM-Tags über Overpass (05.11.2026), darauf die Filter aus tilda-geo. Je Teilsegment zählt die erste `tilda_id`.

| Grund (TILDA-Filter) | km | Beispiele | Kommt in `routingRestricted`? |
|---|---|---|---|
| `bicycle=no` (nur Routing) | 9,1 | Heerstraße (Fahrbahn, Radweg daneben) | Ja. Verliert im Matching gegen den Radweg; 2025 stand dort fälschlich „Mischverkehr“. |
| `vehicle=destination` (nur Routing) | 6,0 | Maronensperlingweg, Walnußweg, Döberitzer Str., Virchowstraße | **Ja**, das ist der eigentliche Bedarf. |
| `access=no` | 5,0 | ehem. Görlitzer Bahn, Bitterfelder Str. | Nein (siehe 3.). |
| `service=driveway` | 1,4 | Friedrich-Engels-Straße (Z239 + 1022-10, `bicycle=yes`) | Nein: Das ist Radinfrastruktur und gehört in die öffentlichen Daten (Regelfehler, siehe 3.). |
| `vehicle=private`, `vehicle=no` | 0,4 | | Ja. |
| Weg gibt es in OSM nicht mehr | 7,3 | | – |

Zusammen 22 km (1,3 % von 1.721 km), 38 Wege, 68 RVN-Elemente. Für REN+ (ganz Berlin) ist mit mehr zu rechnen.

## 2. Heute: geteilte Filter, eine Lücke

Die Filter sind heute schon zwischen den Tabellen geteilt. Das soll so bleiben.

| Stelle | Prüft | Wirkt auf |
|---|---|---|
| `helper/exit_processing.lua` | Highway-Klasse, `area`, Pier/Track, `access` ∈ `private, no, delivery, permit` (dazu `foot` bei `footway`, `bicycle` bei `cycleway`), `service` außer `alley` | ganzer Weg: `bikelanes`, `roads`, `roadsPathClasses`, `routing` |
| `helper/excluded_from_roads_tables.lua` | Sidepath, `indoor`, `informal`, `access` zusätzlich `destination`, `customers` | `roads`, `roadsPathClasses` und die Wege-Kanten in `routing` |
| `routing_infra/inclusion_rules.lua` | `bicycle`, aufgelöst über `vehicle` → `access`, muss erlaubt sein; Autobahn/Kraftfahrstraße | nur `routing` |

Die Lücke: Die ersten beiden prüfen `access` roh, die dritte prüft `bicycle` mit Fallback-Kette. Beispiel `way/6194793` (Radieschenpfad): `access=destination` und `bicycle=yes`. `routing` legt die Fahrbahn-Kante an, `roads` lässt den Weg weg. Das ist sehr wahrscheinlich die Ursache der 112 `roads`-Kanten ohne Partner (siehe tilda-routing.md, § 2).

## 3. Entscheidungen

- **Radieschenpfad-Fall:** Ist Radfahren ausdrücklich erlaubt, kommt der Weg in `roads` / `roadsPathClasses`, auch bei `access=destination|customers`. Prüfen per PBF-Diff-Lauf (Skill `test-processing-diff` in tilda-geo, `reference` gegen `fixed`).
- **Service-Wege mit Radinfrastruktur sind öffentlich.** Heute verwirft `exclude_highways.by_service` jeden `service=*` außer `alley`, bevor die Kategorien laufen. Ausnahme ist nur `bicycle=designated` oder `bicycle:left|right|both`. Dabei sind die Kategorien schon für `highway=service` gebaut (`footAndCyclewayShared`, Z237-Fälle), sie bekommen solche Wege nur nie zu sehen. Neu: Ein schneller Tag-Check entscheidet früh, ob ein `service`-Weg überhaupt Radinfrastruktur haben kann (4.1). Nur diese Kandidaten laufen durch die Kategorien; hat der Weg dann eine eigene Radinfrastruktur (Self-Kategorie mit `infrastructureExists`), ist er öffentlich. Dazu muss `footwayBicycleYes` auch `highway=service` mit Z239 + 1022-10 erkennen; `bicycle=yes` allein reicht dort nicht, weil das auf Zufahrten meist nur „Radfahren erlaubt“ heißt.
  Berlin heute (Overpass, 05.11.2026): 43 `service`-Wege mit Radverkehrszeichen oder `bicycle=designated`. Davon fallen 11 durch die heutige Ausnahme, u. a. 6 × Z239 + 1022-10 (Friedrich-Engels-Straße) und 1 × Z240 ohne `bicycle`-Tag.
- **Inhalt von `routingRestricted`:** alle Kanten, die `routing` aus Zugangs- oder `service`-Gründen weglässt, mit dem Grund in `restriction`:
  - `access`, `vehicle`, `bicycle`, `foot` mit `private`, `delivery`, `permit`, `destination`, `customers`
  - `vehicle=no`, `bicycle=no` (Weg ist für andere offen, nur nicht fürs Rad)
  - `service=*` außer `alley`, `indoor=yes`, `informal=yes`, jeweils nur wenn keine Radinfrastruktur erkannt wurde
- **Gleiche Regel für `indoor` und `informal`.** Erkennen wir eigene Radinfrastruktur, ist der Weg öffentlich, sonst kommt er nach `routingRestricted`. `exit_processing` prüft beides nicht, solche Wege stehen mit Radinfrastruktur also schon in `bikelanes`, und ihre Radinfrastruktur-Kanten stehen in `routing` (die Segmente tragen kein `informal`). Neu ist nur die Zeile in `roads` / `roadsPathClasses` und die Fahrbahn- bzw. Wege-Kante.
- **Nicht aufgenommen:** `access=no`. Temporäre Sperrungen erkennt TILDA bereits über `description`/`note` (`transform_lifecycle_tags.lua`): Der Zugangstag wird entfernt, der Weg bleibt mit `lifecycle=construction_no_access` bzw. `blocked` in den öffentlichen Daten. Was danach noch `access=no` hat, ist dauerhaft gesperrt und gehört nicht ins Radnetz.
- **Weiter ausgeschlossen:** `area`, Pier/Track, Autobahn/Kraftfahrstraße.
- **Name:** `routingRestricted`. Den Namen gibt es in tilda-geo noch nicht; die Exporttabellen heißen camelCase (`roadsPathClasses`, `bikelanesPresence`).

## 4. Konzept in tilda-geo

### 4.1 Stufen: harte Filter früh, feine Entscheidung spät

Heute verlassen rund 20 % aller Wege die Verarbeitung sofort, nur anhand der Tags und vor jeder Geometrie (Deutschland laut taginfo, 05.11.2026: 16,4 Mio. `highway`-Wege, davon 2,6 Mio. mit `service=*`, 1,3 Mio. mit `access=private`; die Mengen überschneiden sich). Das muss so bleiben. Deshalb entscheidet die Verarbeitung in drei Stufen, die ersten beiden nur auf Tags:

| Stufe | Kosten | Prüft | Ergebnis |
|---|---|---|---|
| 1. Harter Ausschluss | Tags | keine/falsche Highway-Klasse, `area`, Pier/Track, `access=no` (nach `transform_lifecycle_tags`) | Abbruch wie heute |
| 2. Einschränkung und Radinfra-Hinweis | Tags | Ist der Weg eingeschränkt (`access`/`vehicle`/`bicycle`/`foot`-Werte, `service`, `indoor`, `informal`)? Wenn ja: Gibt es einen Hinweis auf Radinfrastruktur? | öffentlich, eingeschränkt ohne Hinweis, eingeschränkt mit Hinweis |
| 3. Kategorien | wie heute | nur für „eingeschränkt mit Hinweis“: Hat der Weg eine eigene Radinfrastruktur? | öffentlich oder eingeschränkt |

Hinweis auf Radinfrastruktur (Stufe 2, bewusst großzügig, damit nichts verloren geht): `highway=cycleway`, `bicycle=designated`, `traffic_sign` mit 237, 239, 240, 241, 242, 244 oder 1022, Schlüssel `cycleway*` oder `bicycle:left|right|both`, oder `bicycle=yes` auf `footway`/`path`. Fehlt jeder Hinweis, kann keine Kategorie greifen, und die Kategorien müssen nicht laufen. Wer eine Kategorie ändert, muss diese Liste mitpflegen; ein Test stellt sicher, dass jede Kategorie-Bedingung nur mit mindestens einem Hinweis wahr werden kann.

Neu: `helper/access_restriction.lua`

```lua
--- Stufe 2, nur Tags. Läuft vor Geometrie und Kategorien.
---@return nil | { level: 'way' | 'routing', reason: string, may_have_bike_infra: boolean }
local function access_restriction(object_tags)

--- Stufe 3, nur bei may_have_bike_infra. true = öffentlich.
---@param cycleways table[] Ergebnis der Kategorisierung
local function has_own_bike_infra(cycleways)
```

- `nil`: öffentlich, alle Tabellen wie bisher.
- `level = 'way'`: keine öffentliche Tabelle (`bikelanes`, `roads`, `roadsPathClasses`, `routing`), nur `routingRestricted`. Beispiele: `access=private`, `service=driveway`, `informal=yes`.
- `level = 'roads'`: Radinfrastruktur (`bikelanes` und ihre Routing-Kanten) bleibt öffentlich, keine Zeile in `roads` / `roadsPathClasses`, Fahrbahn- bzw. Wege-Kante in `routingRestricted`. Beispiele: `access=destination` ohne Radfreigabe, `indoor=yes`, `informal=yes`. Entspricht dem heutigen Verhalten von `excluded_from_roads_tables`.
- `level = 'routing'`: öffentliche Tabellen wie bisher, Routing-Kante aber in `routingRestricted` statt `routing`. Beispiele: `vehicle=destination`, `bicycle=no`.
- `reason`: der auslösende Tag, z. B. `vehicle=destination`.

Reihenfolge in `access_restriction`: zuerst `bicycle` über die Kette aus `sanitize_access_tags.resolve`. Ist Radfahren ausdrücklich erlaubt, ist der Weg nicht über Zugangswerte eingeschränkt. Danach die Wertelisten aus 3, dann `service`, `indoor`, `informal`.

`excluded_from_roads_tables` behält Sidepath; Zugang, `indoor` und `informal` wandern in die neue Funktion. `inclusion_rules.exclude_segment` verliert die eigene Zugangs- und `informal`-Prüfung und behält Autobahn/Kraftfahrstraße.

**Gleichlauf:** `exit_processing`, `excluded_from_roads_tables` und `inclusion_rules.exclude_segment` fragen für Zugang, `service`, `indoor` und `informal` nur noch diese Funktionen. Es gibt keine eigene Liste für `routingRestricted`: Die Tabelle bekommt genau das, was die öffentlichen Tabellen aus diesen Gründen weglassen. Änderungen an den Regeln wirken so immer auf `roads`, `bikelanes`, `routing` und `routingRestricted` zugleich. Abgesichert durch die Checks in 4.6.

### 4.2 Ablauf in `roads_bikelanes_ways.lua`

```lua
transform_lifecycle_tags(object_tags)                     -- temporäre Sperrungen → lifecycle
if EXIT.exit_processing(object_tags) then return end      -- Stufe 1, nur Tags
local restriction = access_restriction(object_tags)       -- Stufe 2, nur Tags

if restriction and restriction.level == 'way' and not restriction.may_have_bike_infra then return end

-- … Geometrie, pseudo tags, transforms, result_tags, bikelane state wie bisher …

if restriction and restriction.may_have_bike_infra and has_own_bike_infra(context.cycleways) then
  restriction = nil                                       -- Stufe 3: Radinfrastruktur → öffentlich
end

if restriction and restriction.level == 'way' then
  roads_bikelanes_routing_restricted(context, restriction)  -- volle Zeile, nur diese Tabelle
  return
end

roads_bikelanes_sidepath_source_paths(object_tags, object_geom)
roads_bikelanes_routing_infra(context, restriction)        -- level 'routing' → routingRestricted
roads_bikelanes_bikelanes(context)
roads_bikelanes_roads(context)
```

Kostenfolgen je Fall:
- **Öffentlich:** unverändert. Neu ist nur der Tag-Check aus Stufe 2.
- **`level = 'routing'`** (`vehicle=destination`, `bicycle=no`): Diese Wege laufen schon heute voll durch, weil sie in `roads` stehen. Nur die Routing-Kante geht in eine andere Tabelle.
- **`level = 'way'` ohne Hinweis** (fast alle Zufahrten, Parkplatzgassen, private Wege): sofort verworfen wie bisher.
- **`level = 'way'` mit Hinweis:** volle Verarbeitung. Das sind wenige (Berlin: 43 `service`-Wege, dazu einzelne `informal`/`indoor`-Wege).

Bei `level = 'way'` wird nie in `_roads_bikelanes_sidepath_source_paths`, Fehler-Log, Todos oder Präsenz geschrieben, sonst würden private Wege die öffentlichen Daten beeinflussen.

### 4.3 Zeilen bauen statt schreiben (Refactor)

Eingeschränkte Wege mit `level = 'way'` haben keinen Partner in `roads` oder `bikelanes`. `routingRestricted` trägt die Attribute deshalb selbst. Damit sie nicht doppelt berechnet werden, kommen die Zeilen aus denselben Funktionen:

- `roads_bikelanes_bikelanes.lua` → `build_bikelane_row_tags(context, cycleway)` ausgliedern (heute die Zeilen 31–53).
- `roads_bikelanes_roads.lua` → `build_road_row_tags(context)` ausgliedern (bis zum Cleaner; ohne `excluded_from_roads_tables`, Todos, Inserts).
- Die Writer rufen diese Funktionen auf und schreiben wie bisher. Kein Verhalten ändert sich; die vorhandenen Tests und ein Diff-Lauf sichern das ab.

### 4.4 Tabelle `routingRestricted`

In `roads_bikelanes_tables.lua`, gleiche Spalten und Indizes wie `routing`. Eine Zeile je Kante, gleiche `id`-Regeln wie `routing`.

`tags` =
1. die Routing-Tags aus `build_public_tags` (`category`, `side`, `oneway`, `oneway_motor`, `source_table`, `source_id`, `parent_id`, `road`, …),
2. die vollständige Zeile der Quelle aus 4.3 (Radinfrastruktur: Bikelane-Zeile, sonst Roads-/Wege-Zeile),
3. `restriction` (z. B. `vehicle=destination`, `service=driveway`), `restriction_level` (`way` | `routing`), `access_bicycle`.

`source_table` / `source_id` bleiben. Bei `restriction_level = 'way'` gibt es in der Quelltabelle keinen Partner; das steht in der Doku.

Nicht für `routingRestricted`:
- `4_hide_network_noise.sql`: keine Inseln und Stummel entfernen. Eingeschränkte Wege sind fast immer Stummel und hängen erst zusammen mit `routing` am Netz.
- Kacheln, Statistik, QA, Masterportal.

Größe: Berlin-Brandenburg 38.346 Kanten (nur Stufen `roads` und `routing`).

### 4.5 Export

- `exportIdentifier.ts`: `'routingRestricted'` ergänzen.
- `exportConfigsTilda.const.ts`: Eintrag „Routing-Netz, eingeschränkte Wege (intern)“.
- `topic-docs/roads_bikelanes/routingRestricted.yaml`: Verweis auf `routing.yaml`, dazu `restriction`, `restriction_level`.
- Freischalten nur in der Region Infravelo (`exports`, per Admin oder `regions_update`).

Zugriff: Ohne API-Key prüft der Export die Mitgliedschaft in der Region. Mit dem globalen API-Key geht der Export für jede Region, die die Tabelle freigibt. Solange nur Infravelo sie freigibt, reicht das.

### 4.6 Tests und Prüfung

- `access_restriction.test.lua`: Radieschenpfad (`access=destination`, `bicycle=yes` → `nil`), Heerstraße (`bicycle=no` → `routing`), Maronensperlingweg (`vehicle=destination` → `routing`), `service=driveway` ohne Radinfrastruktur → `way`, `way/34144223` (Friedrich-Engels-Straße, `service=driveway`, Z239 + 1022-10) → `nil` mit `footwayBicycleYes_*`, `service=driveway` mit Z240 ohne `bicycle` → `nil` mit `footAndCyclewayShared_*`, `footway` mit `foot=private` → `way`, `informal=yes`-Pfad ohne Radinfrastruktur → `way`, `informal=yes` mit Z240 ohne `bicycle` → `nil` und Kante in `routing`, `indoor=yes`-Gehweg ohne Radinfrastruktur → `way`, `access=no` → von `exit_processing` verworfen, Baustellen-Sperrung per `description` → `nil` mit `lifecycle`.
- Writer: Ein Weg mit `level = 'way'` erzeugt keine öffentliche Zeile und genau die erwarteten `routingRestricted`-Kanten.
- Radinfra-Hinweis: Für jede Bikelane-Kategorie ein Beispiel, das ohne Hinweis aus Stufe 2 nicht greift. Wird eine Kategorie so geändert, dass sie ohne Hinweis greift, schlägt der Test fehl.
- SQL-Checks nach der Verarbeitung: keine `id` in `routing` und `routingRestricted` zugleich; `routing` → `roads` ohne Fehltreffer (heute 112).
- PBF-Diff-Lauf (`test-processing-diff`) für Berlin: neue Zeilen in `roads` / `roadsPathClasses` (Radieschenpfad-Fall) , in `bikelanes` (Service-Wege mit Radinfrastruktur) und in `routing` (informelle Wege mit Radinfrastruktur) durchsehen, sonst keine Änderungen in den öffentlichen Tabellen.

### 4.7 Geschwindigkeitstest (Pflicht vor jedem Merge)

Die bestehenden Tabellen dürfen nicht langsamer werden. Jeder Schritt aus 6. in tilda-geo bekommt einen Vorher-nachher-Test über Nacht:

- **Gebiet:** Berlin-Brandenburg. Neues Preset `berlin-brandenburg` in `app/scripts/processing-generate-command/bboxPresets.ts` (ca. `11.26,51.35,14.77,53.56`).
- **Läufe:** gleiche PBF, gleiche Maschine, nacheinander, ohne andere Last. Erst `reference` (Basis-Commit), dann `fixed` (neuer Code), je zweimal, damit Ausreißer auffallen. Topic `roads_bikelanes`, Download und Cache-Aufwärmen aus.
- **Messen:** aus `public.meta` je Lauf `topics.roads_bikelanes.lua` und `.sql` (Start/Ende), dazu Gesamtdauer; Zeilen und Größe (`pg_total_relation_size`) von `bikelanes`, `roads`, `roadsPathClasses`, `routing`, `routingRestricted`.
- **Abnahme:** Lua- und SQL-Zeit von `roads_bikelanes` höchstens im Rauschen der zwei Vergleichsläufe (Richtwert +2 %). Die bestehenden Tabellen ändern sich nur um die gewollten Zeilen aus 4.6. Liegt der Lauf darüber: Hinweisliste und doppelte Roads-Zeile prüfen, bevor gemergt wird.
- **Ergebnis** als Tabelle in den PR.

## 5. Nutzung in diesem Repo

1. Export laden: `routingRestricted` als `data/TILDA Routing Eingeschraenkt Berlin.gpkg`, aus demselben Lauf wie `routing`.
2. `prepare_tilda_routing.py`:
   - `routingRestricted` vor `split_at_shared_vertices` an `routing` anhängen, damit die Wege Knoten teilen und in die größte Komponente gelangen.
   - Kein Join für diese Zeilen, die Attribute sind schon da.
   - Spalte `routing_restriction` durchreichen; im Report km je `restriction`.
3. Map-Matching:
   - Neues Prädikat `restricted` (bool) in der Regel-Engine. Die Engine sortiert Tiers nach `rank` und nimmt den ersten Treffer; eingeschränkte Kandidaten bekommen deshalb einen Zuschlag (`rules.restricted_rank_offset = 10`). Sie gewinnen nur, wo keine öffentliche Kante liegt.
   - `tilda_restriction` in `transfer_attributes`, damit die Ausgabe diese Stellen zeigt.
4. Evaluation: km mit `tilda_restriction` je Wert ausweisen.

## 6. Reihenfolge

1. tilda-geo: Preset `berlin-brandenburg`, Basis-Messung über Nacht (4.7).
2. tilda-geo: `access_restriction` (Stufe 2) und `has_own_bike_infra` (Stufe 3) mit Tests, die drei Filter darauf umstellen, `footwayBicycleYes` für `highway=service` mit Z239 + 1022-10. Diff-Lauf und Geschwindigkeitstest. Einzeln mergebar (behebt den Join-Fehler und die fehlenden Service-Radwege).
3. tilda-geo: Row-Builder ausgliedern (reiner Refactor, Diff-Lauf ohne Änderungen, Geschwindigkeitstest).
4. tilda-geo: `routingRestricted` (Stufen `roads` und `routing`, überall), Export, Topic-Doc, Freischaltung Infravelo. Geschwindigkeitstest.
5. Hier: Export laden, `prepare_tilda_routing.py`, Regel-Engine, Evaluation gegen 2025.
