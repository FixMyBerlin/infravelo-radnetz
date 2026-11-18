# map-matching – HMM-/Viterbi-Map-Matching TILDA → RVN

Ersetzt das bisherige Python-Matching und -Snapping der 2025er-Pipeline (archiviert im Tag
`rvn-final-state`). Das Ergebnis ist eine segmentierte Kantendatei
im Format von `snapping_network_enriched.fgb`. Die Python-Folgeschritte (Konvertierung,
Aggregation) können sie direkt weiterverwenden.

## Verwendung

Alle Datenpfade in `config/default.toml` sind relativ zu `processing/`.

```sh
cd processing/map-matching
cargo build --release

# Ganz Berlin (schreibt processing/output/map-matching/network_enriched_hmm.fgb)
cargo run --release -- run

# Region + Debug-Layer + direkte Evaluation gegen die Referenz
cargo run --release -- run --clip neukoelln --debug --eval

# Nur Topologie-Report des RVN
cargo run --release -- topology

# Viterbi-Gitter einzelner TILDA-Wege (JSON)
cargo run --release -- debug-trace --tilda-id way/812944119

# Vorhandene Ergebnisdatei evaluieren (primär bzw. sekundäre Referenz)
cargo run --release -- eval
cargo run --release -- eval --secondary

# Parametergitter durchrechnen (Daten werden einmal geladen)
cargo run --release -- tune --clip neukoelln --grid grid.toml

# Beliebige Konfigurationswerte überschreiben
cargo run --release -- run --set hmm.beta_m=6 --set trace.sample_interval_m=4

# REN+ (alle Netzquellen gemeinsam) statt Radvorrangnetz
cargo run --release -- --netz ren run

# Eingang aus PostGIS (pgRouting-Tabellen aus ../../graph-interface/) statt aus Dateien
MATCHING_PG="host=127.0.0.1 port=5432 dbname=… user=…" PGPASSWORD=… cargo run --release -- --pg run
```

### Eingang aus PostGIS (`--pg`)

Mit `--pg` (oder `--set postgres.enabled=true`) liest das Matching Referenz- und Eingangsnetz aus den Tabellen `matching.reference_edges` und `matching.input_edges` (`[postgres]` in `config/default.toml`), die `graph-interface/load.sh` im pgRouting-Format anlegt. Die Verbindung kommt aus der Umgebungsvariable `MATCHING_PG` (libpq), das Passwort aus `PGPASSWORD` oder `~/.pgpass`.

- Referenznetz: Knoten aus `source`/`target` statt aus Endpunkten innerhalb `network.node_tolerance_m`; Name aus `match_key`. `reverse_cost` wird nicht ausgewertet, gematcht wird gegen beide Richtungen.
- Eingangsnetz: je `paths.tilda[].data_source` die Zeilen mit gleicher `trace_group`, Knoten aus `source`/`target`, Einrichtungswege aus `reverse_cost < 0`, Name aus `match_key`, übertragene Attribute aus `attrs`.
- Bezirke und Zuschnitte (`--clip`) bleiben Dateien aus `[paths]`; die Ausgabe bleibt FlatGeobuf.

### Zwischenergebnis nach dem Matching und `assemble`

Mit `--pg` schreibt `run` zusätzlich die Intervalle nach dem Matching (Stufe 6) nach `postgres.intervals` (Standard `matching.intervals`): je Intervall `ref_id` (id in `reference_edges`), `ri`, `from_m`/`to_m` in Digitalisierungsrichtung der Referenzkante, `input_id` (id in `input_edges`), `input_ref`, `trace_group`, `trace_id`, `score`, `n_obs`, `mirrored` und das Stück der Referenzkante als Geometrie.

`assemble --pg` führt nur die fachliche Stufe 7 (Regel-Engine, Lücken, kurze Stücke, Einbahn-Regel) auf dieser Tabelle aus und schreibt das Ergebnis wie `run`. So lassen sich die Intervalle in PostGIS ändern oder aus anderen Schritten erzeugen (z. B. verkettete Matchings, siehe `graph-interface/osmnexus/`), ohne neu zu matchen.

```sh
cargo run --release -- --pg run                                              # schreibt matching.intervals
cargo run --release -- --pg assemble --set postgres.intervals=matching.intervals_union
```

`network.respect_direction = true` (nur `--pg`) beachtet die Fahrtrichtung des Referenznetzes: `cost < 0` sperrt die Digitalisierungsrichtung, `reverse_cost < 0` die Gegenrichtung, für Kandidaten und Routing. Gespiegelte Intervalle von Zweirichtungswegen landen weiter in beiden Richtungen.

Für ganz Berlin ist das Ergebnis von `assemble` auf den Intervallen eines Laufs in allen Zeilen, Geometrien und Attributen gleich dem Ergebnis des Laufs selbst. Positionen und Güte werden dafür exakt übertragen (GDAL schreibt Gleitkommazahlen sonst nur mit 15 Stellen).

Stand 2026-11-10 (Radvorrangnetz, ganz Berlin): gleiche Kanten-, Knoten- und Trace-Zahlen und eine Ausgabe, die in allen Zeilen, Geometrien und Attributen mit dem Lauf aus den Dateien übereinstimmt.

`--netz rvn|ren` wählt das Zielnetz aus `[netze.*]` in `config/default.toml`. Die Werte dort ersetzen die gleichnamigen in `[paths]` (Netz, TILDA-Routing, Ausgabeordner), `--set` wirkt danach. Ohne `--netz` gilt `[paths]`, also das Radvorrangnetz. `ren` schreibt nach `output/map-matching-ren/` und braucht `../process_radnetz.sh --netz ren` und `../scripts/prepare_tilda_routing.py --netz ren`.

Log-Level über `RUST_LOG` (z. B. `RUST_LOG=debug`). Logs landen zusätzlich in `output/map-matching/logs/`.

Voraussetzungen: Rust ≥ 1.85, GDAL (getestet mit 3.13) und libclang für die GDAL-Bindings.

## Methodik

Die TILDA-Wege sind die „Traces“, die gerichteten RVN-Kanten `(element_nr, ri)` die versteckten Zustände.

1. **Netz** (`src/network`): Knoten entstehen aus Endpunkten, die innerhalb von `network.node_tolerance_m`
   (1 cm, reines Gleitkomma-Rauschen) übereinstimmen. Es wird nichts repariert: Wo das RVN nicht
   topologisch korrekt ist (T-Stöße ohne Knoten, Lücken), gibt es keinen Übergang. Der
   Topologie-Report weist diese Stellen aus.
2. **Traces** (`src/trace`): TILDA-Wege aus Bikelanes, Streets und Paths werden zu Beobachtungen
   abgetastet. Die TILDA-Topologie wird nicht vorausgesetzt.
3. **HMM** (`src/hmm`): Kandidaten sind gerichtete RVN-Kanten im Radius plus ein Null-Zustand
   „nicht auf dem RVN“.
   - Emission: Abstand (Gauß), Kurs, Straßenseite bei Einrichtungs-RVA, Straßenname.
   - Übergang: `-|d_route − d_trace| / β`, mit Routing ohne Wenden auf dem RVN-Graphen.
   - Viterbi läuft im Log-Raum, parallel über alle Traces (rayon).
4. **Aufteilung** (`src/assemble`): Aus dem Viterbi-Pfad werden Intervalle je gerichteter Kante.
   Zweirichtungs-Wege werden auf beide `ri` gespiegelt. Je Elementarstück entscheidet die
   **Regel-Engine** (`[rules]` in der Konfiguration):
   - RVA vor Mischverkehr vor sonstigen Wegen
   - Vorrang des Bussonderfahrstreifens vor einem unbeschilderten Hochbordradweg
   - innerhalb eines Rangs die HMM-Güte

   Danach werden Lücken geschlossen, Kleinstschnipsel entfernt und gleiche Nachbarn verschmolzen.
   Die Einbahn-Regel greift, und freie Abschnitte bekommen „Keine Radinfrastruktur vorhanden“.
5. **Evaluation** (`src/eval`): längengewichteter Vergleich mit der Referenz über lineare
   Referenzierung. Der Bericht enthält Attributquoten, Konfusionsmatrix, Bezirke und den Anteil
   der Abweichungen an Stellen mit manuellen Eingriffen des Altverfahrens.

Die manuellen Listen (`include_ways`, `exclude_ways`, `override_ways`, `opposite_edge_overwrite`)
werden **nicht** verwendet, nur in der Evaluation zur Einordnung.

## Ausgaben (`output/map-matching/`)

| Datei | Inhalt |
|---|---|
| `network_enriched_hmm[_<clip>].fgb` | Ergebnis: Teilsegmente je `(element_nr, ri)` mit TILDA-Attributen, `hmm_konfidenz`, `hmm_regel`, `hmm_kandidaten` |
| `matched_tilda_ways[_<clip>].fgb` | TILDA-Wege mit gematchter und gewonnener Länge |
| `stats[_<clip>].json` | Zählwerte und Laufzeiten |
| `topology_report.fgb/.json` | Topologie-Auffälligkeiten des RVN |
| `debug[_<clip>]/` (`--debug`) | `observations`, `intervals_raw`, `conflicts`, `breaks`, `topology_report` |
| `evaluation[_<clip>]/` | `report.md`, CSVs, `disagreements.fgb` |
| `logs/` | Logdateien je Lauf |
