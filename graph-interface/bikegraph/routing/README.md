# Routing-Matcher (Qualitätssicherung)

Zweite Matching-Option neben dem HMM-Matcher (v7): das RVN wird nicht über Kandidaten je Stelle, sondern über gewichtete
kürzeste Wege durch den Routing-Graphen (TILDA-Routing plus OSM-Topologie) auf die Radinfrastruktur abgebildet. Das
Ergebnis (Führungsform je RVN-Kante und Richtung) wird **nicht abgegeben**; es dient der Qualitätssicherung von v7: wo
beide Verfahren unterschiedlich entscheiden, und wo das Netz auffällig ist (Lücken, unbequeme Verbindungen, sehr lange
Kreuzungen).

## Aufruf

```sh
MATCHING_PG="host=127.0.0.1 port=5433 dbname=postgres user=postgres" PGPASSWORD=... \
  V7_C=processing/output/<v7-Lauf>/post/aggregated.gpkg \
  graph-interface/bikegraph/routing/routing_qa.sh
```

Berlin dauert etwa 15 Minuten (Graph rund 4, Routing rund 10, Bericht 1). Voraussetzungen:

- Datenbank aus der Graph-Pipeline (`graph.sh`, `radweg_faltung.sh`, `datensatz_c.sh`): `bikegraph.edges`, `osm_ways`,
  `bl_input`, `bl_faltung`, `dc_input`, `input_edges` und das RVN in `matching.reference_edges` (dasselbe RVN wie für v7).
- `V7_C`: Datensatz C des v7-Laufs (`aggregated.gpkg` mit den Ebenen `hinrichtung`, `gegenrichtung`) → `bikegraph.c_v7`.
  Wahlweise `BASE_C` (Baseline) → `bikegraph.c_base`.
- `processing/output/bus_stops_on_rvn.fgb` (`processing/scripts/prepare_bus_stops.py`) → `bikegraph.bus_stops`; ohne die
  Datei entfällt die Umwandlung der Schutzstreifen an Haltestellen.
- `psql`, `ogr2ogr`, pgRouting, Python mit `scipy` und `psycopg2` (`requirements.txt`).

## Bericht (`processing/output/routing-qa/`)

| Datei | Inhalt |
|---|---|
| `zusammenfassung.txt` | Übereinstimmung mit v7, Unterschiede nach Urteil, Zahlen je Auffälligkeit |
| `abweichungen_v7.fgb`, `.csv` | jede RVN-Kantenrichtung mit anderer Führungsform als v7, mit **Urteil aus den Belegen vor Ort** (`Routing richtig`, `v7 richtig`, `Grenzfall`, `TILDA-Daten`, `ohne v7`), Grund, Belegen (Formen, Länge und Abstand an der Kante) und Viewer-Link |
| `unbequem.fgb` | Verbindungen, die Routen nur über Treppen, Erschließungsstraßen oder Baustellen finden, und Brücken über Netzlücken |
| `kreuzungen_lang.fgb` | Kreuzungsstücke ab `LANG_M` (Standard 50 m): Umwege an Kreuzungen, oft fehlende Verbindungen im Netz |
| `luecken.fgb` | Abbrüche: Abschnitte ohne durchgehenden Weg mit Abbruchpunkt und grober Ursache (gesperrt, Einbahn, entfernt, Netzlücke) |

Das Urteil (`martin_beurteilung.sql`): offene Kanten des Graphen bis 30 m neben der RVN-Kante, parallel und in
Fahrtrichtung offen; eine Seite gewinnt, wenn ihre Form an der Kante liegt und die andere nicht, wenn ihre Stufe besser ist
und sie mindestens die halbe Kante deckt, oder bei gleicher Stufe deutlich mehr deckt bzw. deutlich näher liegt; sonst
Grenzfall. Es ist ein Hinweis zum Nachsehen, kein Beweis.

## Martin

Eigene Konfiguration `../martin/routing_qa.yaml` mit Style `../martin/styles/routing_qa.json` (Port 3001), damit
`rvn_matching.yaml` ohne die Tabellen des Routing-Matchers startet. Start nach `routing_qa.sh` (Kopf der YAML-Datei):

```sh
docker run -d --name routing-qa-martin --network host -e DATABASE_URL=postgresql://USER:PASS@localhost:5433/postgres \
  -v "$PWD/graph-interface/bikegraph/martin:/cfg:ro" ghcr.io/maplibre/martin:latest --config /cfg/routing_qa.yaml
```

Ebenen im Schema `routing_martin`: `routing_rvn` (Ergebnis je RVN-Kante), `routing_diff_v7`, `routing_urteil_routing`,
`routing_urteil_v7`, `routing_urteil_grenzfall`, `routing_unbequem`, `routing_crossings`, `routing_luecken`,
`routing_routen` (Wege als Vereinigung), `routing_radwege` / `routing_wege` / `routing_strassen` (Routing-Graph),
`routing_haltestellen`, `routing_rvn_diff` (nur nach `rvn_korrektur.sh`). Ändern sich Spalten, schreibt
`python3 martin_konfig.py` (mit `MATCHING_PG`, `PGPASSWORD`) die Konfiguration und den Style neu.

## Verfahren

1. `graph.sql`: Routing-Graph aus `bikegraph.edges` mit Faktor je Kante und Richtung (Radweg 0.5, Streifen 0.65, Busspur
   0.45, geschützter Radfahrstreifen und beschilderter Radweg 0.4, Kreuzungsweg 0.45, Straße 1.0, Sonstige Wege 1.3,
   Gehwege 1.5). Treppen, Erschließungsstraßen und Baustellen sind Zusatzkanten (nur als letzte Option); ausdrücklich für
   den Radverkehr freigegebene Wege (`bicycle=yes/designated`) sind offen; Schutzstreifen an Bushaltestellen werden
   Radfahrstreifen wie in v7.
2. `abschnitte_1_vorbereitung.sql`: gerichtete Abschnitte zwischen Kreuzungen, je Kreuzung und Paar aus ankommendem und
   abgehendem Abschnitt eine Route, Korridor 50 m mit Abstandsterm zur RVN-Linie.
3. `abschnitte_2_routing.sql`: kürzester Weg je Route; ohne durchgehenden Weg als Kette (`abschnitte_2_kette.sql`):
   ein zusammenhängender Weg Stück für Stück entlang der RVN-Kanten, jedes Stück ab dem Ende des bisherigen Wegs, zuletzt
   über Zusatzkanten, Brücken genau an der Lücke (`-v kette=false`: unabhängige Teilrouten je RVN-Kante).
4. `abschnitte_2s_steiner.py`: je Kreuzung alle Routen gemeinsam als Steiner-Wald (MILP): Kanten, die schon eine Route
   benutzt, kosten nur noch einen Teil (`STEINER_LAMBDA`), über alle Kreuzungen geteilt. Das gibt einheitliche, kurze
   Kreuzungen statt paralleler Umwege.
5. `abschnitte_3_auswertung.sql`: die ganzen Routen auf die RVN-Kanten ihrer Abschnitte projiziert, Führungsform je Stelle
   nach Stufe (Radinfrastruktur vor Mischverkehr vor Sonstigen Wegen, Stufen wie `rules.tiers` von v7) und Zahl der
   Routen, je Kante die längste. Vorher die Vorrangregeln von v7 (`rules.prefer`): Bussonderfahrstreifen vor Radweg ohne
   Z237/240/241, geschützter Radfahrstreifen vor Bussonderfahrstreifen (`-v vorrang=false` schaltet ab).
6. `abschnitte_4_kandidaten.sql`: parallele Radinfrastruktur neben dem Weg als Kandidat (bessere Stufe oder Vorrang wie
   v7 bei kleinem Umweg).
7. `luecken.sql`, `martin.sql`, `qa_bericht.sql`: Abbrüche, Martin-Ebenen, Zusammenfassung.

Stand Berlin (geteilter Steiner, λ = 0.3, Kette, Vorrang): 9978 von 10325 RVN-Kantenrichtungen wie v7; von den Unterschieden urteilt die
Beurteilung etwa ein Drittel für das Routing, ein Fünftel für v7, der Rest sind Grenzfälle.
