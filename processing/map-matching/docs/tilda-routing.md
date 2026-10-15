# TILDA-Routing-Netz für das Map-Matching (Workdoc)

Stand: 15.10.2026. Ziel: Map-Matching nur mit topologisch korrekten Daten.

## 1. Daten

| Datei | Herkunft |
|---|---|
| `data/TILDA Routing Berlin.gpkg` | `GET https://tilda-geo.de/api/export/berlin/routing?format=gpkg` (Tabelle `routing`). Stand 15.10.2026 lokal mit tilda-geo gerechnet (Commit `ef5dc0473`), Ergebnis identisch zum API-Export. |
| `data-raw-tilda/{bikelanes,roads,roadsPathClasses}.fgb` | gleiche API, Tabellen `bikelanes`, `roads`, `roadsPathClasses`. **Müssen aus demselben Verarbeitungslauf stammen wie `routing`.** |

`routing` enthält alle drei Netzarten in einer Tabelle. Die Spalte **`source_table`** sagt, woher eine Kante stammt:

| `source_table` | Inhalt | `category` | Kanten / km |
|---|---|---|---|
| `bikelanes` | Radinfrastruktur (links/rechts/self) | z. B. `cycleway_adjoining`, `crossing` | 39.077 / 3.055 |
| `roads` | Fahrbahn | `mixedTrafficMotor` | 101.361 / 7.293 |
| `roadsPathClasses` | Wege ohne Radinfrastruktur | `mixedTrafficFoot` | 115.286 / 6.432 |

Ein separater Roads-Datensatz ist also nicht nötig. Radstreifen links/rechts liegen auf der Fahrbahn-Mittellinie (geometrisch doppelt); die Seite steht in `side` und `offset`.

## 2. Join der Attribute

`routing` enthält keine vollständigen Tags. Die Fachattribute (Verkehrszeichen, Breite, Trennung …) kommen über den Schlüssel aus der Quelltabelle (tilda-geo: `processing/topics/roads_bikelanes/routing_infra/README.md`):

```
routing.source_table = 'bikelanes'        → bikelanes.id        = routing.source_id
routing.source_table = 'roads'            → roads.id            = routing.source_id
routing.source_table = 'roadsPathClasses' → roadsPathClasses.id = routing.source_id
```

Als SQL in der tilda-geo-Datenbank:

```sql
SELECT r.id, r.geom, r.tags AS routing_tags,
       COALESCE(b.tags, rd.tags, p.tags) AS source_tags
FROM routing r
LEFT JOIN bikelanes b           ON r.tags->>'source_table' = 'bikelanes'        AND b.id  = r.tags->>'source_id'
LEFT JOIN roads rd              ON r.tags->>'source_table' = 'roads'            AND rd.id = r.tags->>'source_id'
LEFT JOIN "roadsPathClasses" p  ON r.tags->>'source_table' = 'roadsPathClasses' AND p.id  = r.tags->>'source_id';
```

Im Repo passiert derselbe Join auf den Export-Dateien (`prepare_tilda_routing.py`):
- Geometrie und Richtung kommen aus `routing` (geprüft: identisch zur Quelltabelle, 21 von 255.724 umgedreht).
- Routing-Attribute heißen `routing_*`, Quellattribute behalten ihren Namen (danach `tilda_*`).
- Fehlt `oneway` in der Quelle (bei Wegen fast immer), gilt `routing_oneway`.
- Fehlt das Quellobjekt, gelten gleichnamige Routing-Attribute. Abbruch bei mehr als 1 % Fehltreffern je Tabelle (Hinweis auf unterschiedliche Verarbeitungsläufe; mit den Januar-Dateien fehlen rund 8 % der Kilometer).

Bekannter Fehler in tilda-geo: 112 `roads`-Kanten (14 km, meist `residential`/`service_road`) haben keine Zeile in `roads`, z. B. `way/6194793`. Die README dort verspricht 0 Fehltreffer.

## 3. Topologie

OSM-Wege enden nicht an jeder Kreuzung: 82.826 Endpunkte liegen auf einem *inneren* Stützpunkt eines anderen Wegs. Deshalb wird jeder Weg an jedem Stützpunkt geteilt, den er mit einem anderen Weg teilt (Toleranz 1e-7°, ca. 1 cm, nur Gleitkomma-Rauschen, keine Reparatur). Ergebnis: 255.724 Wege → 500.365 Kanten mit `from_node`/`to_node`.

Zusammenhang (größte Komponente nach Länge):

| | Hauptnetz | außerhalb |
|---|---|---|
| bikelanes | 3.042 km (99,5 %) | 15 km |
| roads | 7.228 km | 68 km |
| roadsPathClasses | 5.548 km | 887 km |

Außerhalb liegen fast nur Fußwege (822 km `footway`, dazu Treppen, Feldwege, Zufahrten): Gehweg-Inseln in Parks, auf Friedhöfen und Plätzen, deren Anschluss über Gehwege läuft, die tilda-geo nicht im Routing führt. Diese Kanten werden **ausgeschlossen** (`ausserhalb_hauptnetz.fgb` zum Prüfen). Abbruch, wenn weniger als 95 % der Radinfrastruktur im Hauptnetz liegen.

Danach: Zuschnitt auf den RVN-Puffer (33 m, ganze Kanten) und Übersetzung in RVN-Attribute mit `translate_attributes_tilda_to_rvn.py`.

## 4. Reproduzieren

```sh
cd processing
# 1. Exporte laden (gleicher Verarbeitungsstand!)
curl -o "data/TILDA Routing Berlin.gpkg"   "https://tilda-geo.de/api/export/berlin/routing?format=gpkg&apiKey=$KEY"
for t in bikelanes roads roadsPathClasses; do
  curl -o "data-raw-tilda/$t.fgb" "https://tilda-geo.de/api/export/berlin/$t?format=fgb&apiKey=$KEY"
done
# 2. Join, Topologie, Hauptnetz, Übersetzung (~7 min)
../.venv/bin/python scripts/prepare_tilda_routing.py
```

Ausgabe in `output/TILDA-routing/`: `TILDA Routing {Bikelanes,Streets,Paths} Translated.fgb`, `ausserhalb_hauptnetz.fgb`, `report.json`.

## 5. Map-Matching mit Topologie-Traces

Begriffe: **Beobachtung** = ein Punkt auf einer TILDA-Kante (alle 5 m), der zugeordnet werden soll. **Zustand** = eine gerichtete RVN-Kante, auf die er fallen kann. **Trace** = eine Folge von Beobachtungen, die Viterbi gemeinsam als zusammenhängenden Pfad löst. Die Attribute fließen weiter von TILDA auf das RVN.

`trace.strategy = "topology"` (Code: `src/trace/chain.rs`): Eine Trace läuft von Knoten zu Knoten nur über Kanten derselben Datenquelle (Radweg bleibt Radweg, Fahrbahn bleibt Fahrbahn), Einrichtungswege nur vorwärts. An Verzweigungen nimmt sie die Kante mit der kleinsten Richtungsänderung, höchstens `max_turn_deg` = 45°. Die Richtung an den Kantenenden wird über `end_heading_m` = 10 m gemessen, damit kleine Knicke am Knoten nicht zählen. Biegt eine Kante stärker ab, beginnt sie eine eigene Trace und wird trotzdem gematcht. Jede Kante gehört zu genau einer Trace. Doppelte Geometrien (Radstreifen auf der Fahrbahn) sind getrennte Traces; die Regel-Engine entscheidet: RVA vor Mischverkehr vor Wegen.

Berlin: 130.903 Kanten → 25.575 Traces (19.120 aus mehreren Kanten).

## 6. Vergleich mit der Referenz

Referenz: `output/reference-legacy/snapping_network_enriched.fgb`, das Snapping-Ergebnis des Altverfahrens (gleiche Pipeline-Stufe, identisch mit `output/snapping_network_enriched.fgb`).

So wird verglichen (`map-matching run --eval`, Code: `src/eval/mod.rs`):
1. Referenz und Ergebnis werden linear auf das RVN referenziert: Jedes Teilsegment wird über `element_nr` und `ri` einer gerichteten RVN-Kante zugeordnet. Seine Stützpunkte werden auf die Kante projiziert (max. 2 m Abstand), daraus ergibt sich der Abschnitt von–bis in Metern.
2. Je gerichteter Kante werden alle Abschnittsgrenzen beider Datensätze zusammengelegt. Für jedes Stück dazwischen wird geprüft, ob Referenz und Ergebnis denselben Wert haben.
3. Die Übereinstimmung ist längengewichtet: `fuehr`-Übereinstimmung = übereinstimmende Länge / Referenzlänge. Die anderen Attribute beziehen sich auf die Länge, die beide abdecken.
4. Die manuellen Listen des Altverfahrens (include/exclude/override/opposite_edge) nutzt das neue Verfahren nicht. Abweichungen an diesen Stellen werden extra ausgewiesen.

Ergebnis (15.10.2026, Routing-Netz mit Topologie-Traces):

**Aktueller Stand nach Anpassungen:** `fuehr` **92,2 %** (ohne manuell beeinflusste Stellen 93,2 %, Abdeckung 100 %). Geändert:
- `hmm.candidate_radius_m` 25 → 30 m (allein ohne Wirkung: die zusätzlichen Kandidaten fielen in den Null-Zustand)
- `hmm.sigma_distance_m` 7 → 10 m (91,3 → 92,1 %; getestet auch `null_log_emission` −8: 92,0 %)
- Regel „Geschützter Radfahrstreifen vor Bussonderfahrstreifen“ (92,1 → 92,2 %). Grund: Radstreifen aus dem Routing-Netz liegen auf der Fahrbahn-Mittellinie und gewinnen sonst über die Güte gegen eigenständig kartierte Radwege (Beispiel `43520039_42520034.01`). Allgemeinere, noch offene Lösung: Radstreifen um `offset` verschieben.

Erster Stand vor den Anpassungen:

| Kennzahl | Wert |
|---|---|
| **`fuehr`-Übereinstimmung** | **91,3 %** von 1.699,6 km |
| ohne Stellen mit manuellen Eingriffen | 92,4 % |
| Abdeckung der Referenz | 99,9 % |
| `verkehrsri` / `pflicht` / `ofm` / `farbe` | 95,6 / 96,1 / 94,0 / 96,2 % |
| `protek` / `trennstreifen` / `nutz_beschr` | 97,7 / 97,0 / 97,7 % |
| `breite` / `tilda_id` | 75,2 / 58,9 % |

Größte Verwechslungen (Referenz → neu): Sonstige Wege → Mischverkehr 29,4 km, Radweg → Mischverkehr 15,1 km, Sonstige Wege → keine Radinfrastruktur 11,5 km. Die TILDA-Daten sind von Oktober 2026, die Referenz beruht auf den TILDA-Daten von Januar 2026. Ein Teil der Abweichungen kann deshalb auf Änderungen in OSM zurückgehen; das ist nicht herausgerechnet.

Ausführlicher Bericht (je Bezirk, Verwechslungsmatrix, Abweichungen als Karte): `output/map-matching/evaluation/primaer_snapping/` (`report.md`, `confusion_fuehr.csv`, `disagreements.fgb`).

```sh
cd processing/map-matching && cargo run --release -- run --eval
```
