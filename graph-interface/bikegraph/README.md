# Datensatz C aus dem Radnetz-Graphen (Radweg-Faltung)

Erzeugt Datensatz B und C für das Radvorrangnetz (RVN) aus dem TILDA-Routing-Export: Radwege werden auf die Straßen
gefaltet, Straßen (mit ihren Radwegen als Kandidaten) und Wege auf das RVN gematcht, danach wie bisher `assemble`,
Konvertierung und Aggregation. Alle Schritte laufen in derselben PostGIS-Datenbank wie tilda-geo; alle Tabellen liegen
in den Schemas `bikegraph`, `radweg_faltung` und `datensatz_c`.

## Eingänge

| Quelle | Woher | Wofür |
|---|---|---|
| `public.routing` | tilda-geo (`routing_infra`), mit `tunnel`, `dual_carriageway`, `roundabout`, `_oneway_flip` | welche Stücke Straßen, Wege, Radwege sind; Richtungen; Straßennetz |
| `public.bikelanes`, `public.roads`, `public."roadsPathClasses"` | tilda-geo | Attribute je Kandidat (übersetzt wie `processing/scripts/translate_attributes_tilda_to_rvn.py`) |
| OSM-Auszug (`PBF`) | Geofabrik, Datenstand wie tilda-geo | nur die Knotenlisten: welche Wege sich berühren |
| `matching.reference_edges` | `../load.sh` (RVN aus `processing/`, mit `data/rvn_korrekturen.csv`) | Referenznetz |
| Baseline | `processing/output/…/aggregated.gpkg` eines früheren Laufs | nur der Vergleich |

Straßen kommen nur aus `public.routing`; die OSM-Topologie verbindet nur die Stücke.

## Ablauf

```sh
export MATCHING_PG="host=… port=… dbname=… user=…" PGPASSWORD=…
(cd processing/map-matching && cargo build --release)
./graph-interface/load.sh                               # matching.reference_edges (einmal je RVN-Stand)
./graph-interface/bikegraph/graph.sh                    # Eingang und Topologie
./graph-interface/bikegraph/radweg_faltung.sh           # Radwege auf Straßen falten
OUT_DIR=output/mm-datensatz-c ./graph-interface/bikegraph/datensatz_c.sh   # Datensatz B und C, Vergleich, Martin
```

1. **`graph.sh`** (rund 1,5 min)
   - `sql/04_input.sql`, `sql/05_input.sql`: je TILDA-Objekt eine Zeile mit übersetzten Attributen →
     `bikegraph.input_edges`. `sql/04` ist ein SQL-Port der Python-Übersetzung (auf allen Objekten gleich); Regeländerungen
     müssen in beiden Fassungen erfolgen.
   - `osm_nodes.py`, `sql/20_topology.sql`: jeder OSM-Weg an gemeinsamen Knoten in Kanten geteilt (`bikegraph.edges`),
     Netz je Kante (R/D Fahrbahn, S Radweg und Weg, C Verbindung), Richtungen aus `public.routing`, Radstreifen je
     Elternweg und Seite (`bikegraph.side_objects`).
2. **`radweg_faltung.sh`** (rund 40 s)
   - `sql/100_radweg_eingang.sql`: Straßennetz `bl_strassen1` = alle Fahrbahnkanten mit routing-Zeile, ohne Tunnel;
     Radwege `bl_input` (separate Radwege und Radstreifen).
   - Separate Radwege mit TILDA-Kategorie `*_isolated` (TILDA: nicht neben einer Straße) werden nicht gefaltet: sie
     fehlen im Eingang der Durchgänge (`bl_input1`) und gehen ungefaltet in den RVN-Schritt (`ISOLIERT_FALTEN=true`
     faltet sie wie früher mit).
   - Matcher Durchgang 1 (Richtung beachtet), Durchgang 2b (Zweirichtungs-Radwege auf Straßen in beiden Richtungen) und
     2e (Einrichtungs-Radwege auf Straßen mit umgedrehten Einbahnen) für Radwege unter 50 % gefaltet.
   - `sql/101_radweg_ergebnis.sql`: `bikegraph.bl_faltung` (welcher Radweg auf welchem Stück welcher Straßenkante) und
     die Martin-Tabellen im Schema `radweg_faltung`.
3. **`datensatz_c.sh`** (rund 3 min, Ausgabe in `processing/<OUT_DIR>/`)
   - `sql/104_datensatz_c_eingang.sql`: Eingang fürs RVN-Matching mit zwei trace_groups: `strassen` (Kanten von
     `bl_strassen1`) und `wege` (routing-Wege, ungefaltete Radwege, ungefaltete Reste ab `REST_MIN_M`).
   - Matcher `run --pg` auf `matching.reference_edges` → `bikegraph.dc_iv_raw`.
   - `sql/105_datensatz_c_intervalle.sql`: Wege mit ihrem Objekt, Straßen mit allen Kandidaten ihrer Kante und Richtung
     (Straße, Radstreifen, gefaltete Radwege) auf den gematchten RVN-Abschnitt projiziert → `bikegraph.intervals_dc`.
   - `assemble` (eigene Konfiguration: `default.toml` plus Vorrang konkreter Führungsformen vor „[TODO] Klärung
     notwendig“) → `network_enriched_hmm.fgb`; Konvertierung → `post/converted.fgb` (**Datensatz B**); Aggregation
     (`aggregate_parallel.py`) → `post/aggregated.gpkg` (**Datensatz C**, Ebenen `hinrichtung`, `gegenrichtung`).
   - `compare_c.sh` + `sql/70_compare_c.sql`: Vergleich mit der Baseline je RVN-Kante und Richtung (nur die Richtungen,
     die das RVN vorsieht) → `vergleich_baseline.csv`, `bikegraph.c_faelle`.
   - `sql/106_datensatz_c_martin.sql`: Schema `datensatz_c` für Martin.
   - Vergleich und Martin-Ebenen (Schritte 5 und 6) laufen nur, wenn die Baseline-Datei (`BASELINE`) existiert
     (`VERGLEICH=auto`); `VERGLEICH=0` überspringt sie, `VERGLEICH=1` erzwingt sie. Der Datensatz C ist nach Schritt 4
     fertig.

Die Konvertierung braucht `processing/output/bus_stops_on_rvn.fgb` (aus `processing/process_radnetz.sh`); fehlt die
Datei, entfallen die Schutzstreifen-Umwandlungen an Bushaltestellen.

## Routing-Matcher (Qualitätssicherung)

`routing/routing_qa.sh` bildet das RVN als zweite Matching-Option über gewichtete Wege durch einen Routing-Graphen ab und
vergleicht das Ergebnis mit v7: Unterschiede mit Urteil, unbequeme Verbindungen, lange Kreuzungen und Abbrüche als Bericht in
`processing/output/routing-qa/` und als Martin-Ebenen (Schema `routing_martin`). Nicht für die Abgabe; siehe
`routing/README.md`.

## Martin

`martin/rvn_matching.yaml` (Start siehe Kopf der Datei) zeigt die Ebenen beider Schemas; Kachel-Cache aus, damit neu
gebaute Tabellen sofort sichtbar sind.
