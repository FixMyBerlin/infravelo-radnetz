# Bearbeitungsstand

`load_status.py` liest, welche Linien im Mapping-Editor ([radnetz-mapping.netlify.app](https://radnetz-mapping.netlify.app/)) als erledigt markiert sind. Es hat kein eigenes Ergebnis, sondern wird von zwei Skripten aufgerufen, bevor sie ihre Daten schreiben.

Der Editor speichert die Markierung „Done“ je Linie in der [key-value-db](https://github.com/FixMyBerlin/key-value-db), nicht in OSM. Jede Aufgabe hat dort ein eigenes Projekt. Ein Eintrag bedeutet erledigt; nimmt jemand die Markierung zurück, ist der Eintrag weg. Es gibt nur diese zwei Zustände.

| Aufgabe | Projekt in der key-value-db | id des Eintrags | Skript |
|---|---|---|---|
| Kartierung des Netzes | `infravelo-tracker` | `lfd_nr` der Netzkante | `mapping-zuteilung/assign_accounts.py` |
| Radwege an der Mittellinie (`track`) | `infravelo-track-tracker` | `id` des Wegs, z. B. `way/123/cycleway/right` | `maproulette-centerline-tracks/extract_centerline_tracks.py` |

## Attribute

Beide Skripte ergänzen je Linie:

| Attribut | Inhalt |
|---|---|
| `bearbeitungsstand` | `erledigt` oder `offen` |
| `erledigt_von` | OSM-Name der Person, die markiert hat |
| `erledigt_am` | Datum der Markierung |

Die Gebiete der Zuteilung bekommen zusätzlich `km_erledigt` und `erledigt_prozent`.

## Cache

Jeder Abruf wird mit Zeitpunkt in `cache/<aufgabe>.json` abgelegt (nicht versioniert). Ist die API nicht erreichbar, verwendet das Skript diesen Stand und meldet das im Log. Das Lesen braucht keinen Login; die API verlangt nur den `Origin` des Editors, den das Skript mitschickt.

## Stand in TILDA aktualisieren

Ein Befehl macht alles:

```bash
bearbeitungsstand/update.sh              # Ziel: production
bearbeitungsstand/update.sh --env staging
```

Er ruft beide Skripte auf (beide lesen die key-value-db), trägt den Zeitpunkt des Abrufs in `description` und `dataUpdatedNote` der drei Datensätze in `tilda-static-data` ein (`infravelo-ren-netz-zuteilung-netz`, `infravelo-ren-netz-zuteilung-gebiete`, `infravelo-ren-kartierung-tracks`), committet und pusht `tilda-static-data` und lädt die drei Datensätze nach TILDA hoch. Erledigte Linien sind dort grün unterlegt.

Voraussetzungen: `tilda-static-data` und `tilda-geo` liegen als Geschwister-Ordner neben diesem Repo (sonst `TILDA_STATIC_DATA_DIR` und `TILDA_GEO_DIR` setzen); in `tilda-geo` ist die `.env` mit S3-Zugang und dem Atlas-Key des Ziels eingerichtet (siehe `app/scripts/StaticDatasets/README.md`).

Nimmt die Zuteilung neue Kanten auf, bricht der Befehl vor dem Upload ab: erst `mapping-zuteilung/assignment.csv` committen und pushen, dann erneut starten. Sonst könnte ein Lauf anderswo dieselben Nummern anders vergeben.

Meldet das Log erledigte Linien, die nicht mehr im Datensatz stehen, hat sich deren id geändert oder die Linie ist entfallen.
