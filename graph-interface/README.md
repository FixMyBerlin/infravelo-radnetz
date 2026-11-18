# Graph-Schnittstelle (pgRouting)

Lädt Referenznetz und Eingangsnetz des Map-Matchings als Kantentabellen im [pgRouting-Format](https://docs.pgrouting.org/latest/en/pgRouting-concepts.html#graphs) nach PostGIS. Das ist die Schnittstelle zwischen der Vorverarbeitung (hier im Repo) und einem allgemeinen Matching, das nur zwei solche Tabellen braucht.

```bash
MATCHING_PG="host=127.0.0.1 port=5432 dbname=… user=…" ./graph-interface/load.sh            # Radvorrangnetz
MATCHING_PG="…" ./graph-interface/load.sh --netz ren                                        # REN+
```

Passwort über `PGPASSWORD` oder `~/.pgpass`. Voraussetzung: `processing/process_radnetz.sh` und `processing/scripts/prepare_tilda_routing.py` sind für dasselbe Netz gelaufen. Am Ende laufen die Prüfungen aus `sql/03_checks.sql`.

## Tabellen (Schema `matching`, EPSG:25833, Meter)

### `reference_edges` und `reference_vertices`

| Spalte | Inhalt |
|---|---|
| `id`, `source`, `target` | Kante und Knoten |
| `cost`, `reverse_cost` | Länge; für den Radverkehr in beiden Richtungen, also `reverse_cost = cost` |
| `match_key` | normalisierter Straßenname (optional, für den Namensterm) |
| `geom` | LineString |
| `element_nr`, `part`, `beginnt_bei_vp`, `endet_bei_vp`, `strassenname`, `verkehrsrichtung`, `edge_source` | Attribute des Referenznetzes; `part` ist der Teil eines MultiLineStrings |

Die Knoten entstehen wie im Rust-Matching: Kantenenden, die transitiv höchstens 1 cm auseinander liegen, sind ein Knoten (`ST_ClusterDBSCAN`). Jeder Teil eines MultiLineStrings ist eine eigene Kante. Es wird nichts repariert.

### `input_edges` und `input_vertices`

| Spalte | Inhalt |
|---|---|
| `id`, `source`, `target` | Kante und Knoten; Knoten aus `from_node`/`to_node` von `prepare_tilda_routing.py` |
| `cost`, `reverse_cost` | Länge; `reverse_cost = -1` für Einrichtungswege (nur in Digitalisierungsrichtung) |
| `trace_group` | `bikelanes`, `streets` oder `paths`; Traces laufen nur innerhalb einer Gruppe |
| `match_key` | normalisierter Straßenname (`tilda_name`) |
| `input_ref` | `tilda_id` |
| `geom` | LineString |
| `attrs` | alle übrigen Spalten als `jsonb` (TILDA, Routing, übersetzte Attribute wie `fuehr`, `breite`, `protek`) |

`matching.normalize_match_key()` normalisiert Namen wie `normalize_name` im Rust-Matching.

## Abgleich mit dem Rust-Matching

Stand 2026-11-10, Radvorrangnetz, ganz Berlin:

| | Rust-Matching (Log) | `matching.*` |
|---|---|---|
| Referenz: Kanten / Knoten / Komponenten | 5.294 / 5.055 / 10 | 5.294 / 5.055 / 10 |
| Eingang: Kanten | 130.734 | 130.734 |
| Eingang: Einrichtungswege | – | 60.307 (= Summe `Einrichtungsverkehr` der drei Dateien) |

Das Eingangsnetz zerfällt beim Radvorrangnetz in viele Komponenten (2026-11-10: 1.349, größte mit 89.960 von 95.317 Knoten), weil `prepare_tilda_routing.py` nach der Komponentenwahl auf den RVN-Puffer zuschneidet.

## Noch offen

- Das Rust-Matching liest die Tabellen mit `--pg` (siehe [map-matching/README.md](../processing/map-matching/README.md#eingang-aus-postgis---pg)); ohne `--pg` weiter die FlatGeobuf-Dateien. Die Intervalle schreibt es noch nicht nach PostGIS.
- `source`/`target` des Eingangsnetzes kommen aus gemeinsamen Koordinaten. Liefert tilda-geo sie aus den OSM-Knoten-IDs, ändert sich nur `sql/02_input.sql`.
- `attrs` enthält noch TILDA-spezifische Fachattribute (`fuehr`, `tilda_oneway`, `tilda_category`, `tilda_traffic_sign`), die das Matching für Regeln und Sonderfälle liest.

## pgRouting

Die Tabellen funktionieren direkt mit pgRouting, z. B.:

```sql
SELECT count(DISTINCT component) FROM pgr_connectedComponents(
  'SELECT id, source, target, cost, reverse_cost FROM matching.reference_edges');   -- 10
```

Das Image von tilda-geo (`ghcr.io/baosystems/postgis:17-3.5`, Debian 11) enthält pgRouting nicht. Lokal nachinstallieren (gilt bis zum Neuanlegen des Containers):

```bash
docker exec db sh -c 'echo "deb [ signed-by=/usr/local/share/keyrings/postgres.gpg.asc ] http://apt-archive.postgresql.org/pub/repos/apt bullseye-pgdg main 17" > /etc/apt/sources.list.d/pgdg.list && apt-get update && apt-get install -y postgresql-17-pgrouting'
docker exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS pgrouting"'
```

Debian 11 liegt bei PGDG nur noch im Archiv (`apt-archive.postgresql.org`).
