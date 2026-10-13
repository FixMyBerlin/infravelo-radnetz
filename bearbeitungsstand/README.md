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

## Stand in TILDA

Das Log nennt den Zeitpunkt des Abrufs (`Bearbeitungsstand vom …`). Nach einem Lauf diesen Zeitpunkt in die `description` der drei Datensätze in `tilda-static-data` eintragen (`infravelo-ren-netz-zuteilung-netz`, `infravelo-ren-netz-zuteilung-gebiete`, `infravelo-ren-kartierung-tracks`) und sie neu hochladen. Erledigte Linien sind dort grau und dünn dargestellt.

Meldet das Log erledigte Linien, die nicht mehr im Datensatz stehen, hat sich deren id geändert oder die Linie ist entfallen.
