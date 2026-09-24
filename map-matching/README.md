# map-matching – HMM-/Viterbi-Map-Matching TILDA → RVN

Ersetzt das bisherige Matching (`start_matching.py`) und Snapping (`start_snapping.py`),
die jetzt unter [`legacy/`](../legacy/) liegen. Das Ergebnis ist eine segmentierte Kantendatei
im Format von `snapping_network_enriched.fgb`. Die Python-Folgeschritte (Konvertierung, Overrides,
Aggregation) können sie direkt weiterverwenden.

## Verwendung

```sh
cd map-matching
cargo build --release

# Ganz Berlin (schreibt output/map-matching/network_enriched_hmm.fgb)
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
```

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
