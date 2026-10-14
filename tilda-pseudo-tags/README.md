# TILDA-Pseudo-Tag `infravelo_netz`

[`infravelo-netz.csv`](./infravelo-netz.csv) sagt TILDA bei der Prozessierung, welche OSM-Wege und abgeleiteten Seitenwege zum infraVelo-Radnetz gehören und mit welcher Klasse. Plan und Hintergrund: [FixMyBerlin/private-issues#3755](https://github.com/FixMyBerlin/private-issues/issues/3755).

Es gibt nur **eine** CSV für das Projekt. Sie kommt aus dem Endergebnis der jeweils letzten Lieferung: jetzt Datensatz C 2025, später die Lieferung 2026. Jede neue Lieferung ersetzt sie. Die Datei ist eingecheckt; TILDA lädt sie aus dem Repo:

https://raw.githubusercontent.com/FixMyBerlin/infravelo-radnetz/main/tilda-pseudo-tags/infravelo-netz.csv

```bash
.venv/bin/python tilda-pseudo-tags/build_csv.py                                                    # Lieferung 2025 (Datensatz C)
.venv/bin/python tilda-pseudo-tags/build_csv.py --input processing/output/aggregated_rvn_final.geojson.gz   # neues Ergebnis
```

`processing/copy_to_tilda_static.sh` ruft das am Ende mit dem neuen Ergebnis auf. Danach die geänderte CSV committen und pushen.

## Format

```
osm_id,id_suffix,infravelo_netz
812944114,,V
4425411,cycleway/left,V
```

| Spalte | Inhalt |
|---|---|
| `osm_id` | numerische Way-ID |
| `id_suffix` | zweiter Teil der TILDA-ID: leer für den Weg selbst, sonst z. B. `cycleway/left`, `sidewalk/right` |
| `infravelo_netz` | `V` Radvorrangnetz, `E` Radergänzungsnetz, `S` sonstiges REN+-Netz (Kanten ohne Radverkehrsnetz) |

- Eine Zeile je TILDA-ID, sortiert nach `osm_id` (numerisch) und `id_suffix`, damit sich Lieferungen zeilenweise vergleichen lassen.
- Gehört eine ID zu Kanten verschiedener Klassen, gilt die höhere (V vor E vor S).
- Die Klasse kommt aus der Spalte `radverkehrsnetz` des Ergebnisses. Die Lieferung 2025 hat diese Spalte nicht; sie enthält nur das Radvorrangnetz, also ist dort alles `V`.
- Quelle sind die TILDA-IDs je Netzkante (`tilda_ids`). Kanten ohne IDs fehlen in der CSV.
- Unkomprimiert eingecheckt: Git komprimiert ohnehin, und nur so bleibt der Diff zwischen zwei Lieferungen lesbar.

## Stand

| | |
|---|---|
| Quelle | Lieferung 2025 (Datensatz C) |
| Erzeugt | 2026-10-14 |
| Zeilen | 18.998 (17.420 OSM-Wege), 348 KB |
| `id_suffix` | Weg selbst 12.290, `cycleway/right` 5.076, `cycleway/left` 1.598, `sidewalk/right` 29, `sidewalk/left` 5 |
| `infravelo_netz` | alle `V` |
