# TILDA-Pseudo-Tag `infravelo_netz`

Erzeugt die CSV, mit der TILDA bei der Prozessierung erkennt, welche OSM-Wege und abgeleiteten Seitenwege zum infraVelo-Radnetz gehören und mit welcher Klasse. Plan und Begründung: [FixMyBerlin/private-issues#3755](https://github.com/FixMyBerlin/private-issues/issues/3755).

Es gibt nur **eine** CSV für das Projekt. Sie kommt aus dem Endergebnis der jeweils letzten Lieferung: jetzt Datensatz C 2025, später die Lieferung 2026. Jede neue Lieferung ersetzt sie.

```bash
./tilda-pseudo-tags/update.sh                                           # Lieferung 2025 (Datensatz C)
./tilda-pseudo-tags/update.sh processing/output/aggregated_rvn_final.geojson.gz   # neues Ergebnis
```

`update.sh` ruft `build_csv.py` und `upload_s3.py` auf. `processing/copy_to_tilda_static.sh` ruft es am Ende mit dem neuen Ergebnis auf.

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

- Eine Zeile je TILDA-ID. Gehört sie zu Kanten verschiedener Klassen, gilt die höhere (V vor E vor S).
- Die Klasse kommt aus der Spalte `radverkehrsnetz` des Ergebnisses. Die Lieferung 2025 hat diese Spalte nicht; sie enthält nur das Radvorrangnetz, also ist dort alles `V`.
- Quelle sind die TILDA-IDs je Netzkante (`tilda_ids`). Kanten ohne IDs fehlen in der CSV.

## Ablage

Privater S3-Bucket von TILDA, Key `pseudo-tags/infravelo-netz.csv`, eine Datei für alle TILDA-Umgebungen. Der Ordner `pseudo-tags/` liegt neben `data-schema/`, `region-uploads/`, `test-data/` und `uploads/`. Die TILDA-Prozessierung lädt die Datei mit ihren S3-Zugangsdaten.

Zugang für den Upload: `tilda-pseudo-tags/.env` aus `.env.example` anlegen und `S3_KEY`, `S3_SECRET`, `S3_REGION`, `S3_BUCKET` aus der `.env` von tilda-geo übernehmen. `.env` und `output/` sind nicht versioniert.

## Stand

| | |
|---|---|
| Quelle | Lieferung 2025 (Datensatz C) |
| Hochgeladen | 2026-10-14 |
| Zeilen | 18.998 (17.420 OSM-Wege) |
| `id_suffix` | Weg selbst 12.290, `cycleway/right` 5.076, `cycleway/left` 1.598, `sidewalk/right` 29, `sidewalk/left` 5 |
| `infravelo_netz` | alle `V` |
