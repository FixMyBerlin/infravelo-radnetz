# Mapping-Zuteilung

Teilt das Kartierungsnetz auf die Mapping-Accounts auf: Pro Bezirk bekommt jeder Account ein zusammenhängendes Gebiet mit ähnlich vielen Netz-Kilometern, damit alle gleichzeitig arbeiten können.

**Seit 2026-11-03 steht die Zuteilung in zwei eingecheckten Tabellen** (siehe unten). Gebiete, Accounts und die Nummern der Kanten (`lfd_nr`) ändern sich nicht mehr: An `lfd_nr` hängen die Markierungen „erledigt“ der Mapper im Editor (key-value-db, Projekt `infravelo-tracker`). Regelmäßig läuft nur noch das Update.

| Phase | Skript | Wann |
|---|---|---|
| Ersterfassung | `assign_accounts.py` | einmalig; bricht ab, solange `assignment.csv` existiert |
| **Update** | `update_assignment.py` | bei jedem neuen Netz und um den Bearbeitungsstand zu übertragen |

Gemeinsam genutzt: `assignment_output.py` (Tabellen der Zuteilung, Bearbeitungsstand, Statistik, Editor-Links, Ausgabe).

## Update (regelmäßig)

```bash
.venv/bin/python mapping-zuteilung/update_assignment.py            # schreibt output/ und ergänzt assignment.csv
.venv/bin/python mapping-zuteilung/update_assignment.py --dry-run  # nur output/, assignment.csv bleibt
```

1. **Kanten zuordnen.** Jede Kante des aktuellen Kartierungsnetzes bekommt über ihre `element_nr` die `lfd_nr`, den Account und den Planungsraum aus `assignment.csv`. Was so nicht passt, wird mit den Zeilen ohne `element_nr` verglichen: Anfangs- und Endpunkt liegen höchstens 3 m auseinander, in beliebiger Richtung. Ändert sich die `element_nr` einer Kante, gilt sie als neu.
2. **Neue Kanten einflechten.** Eine Kante ohne Gegenstück bekommt den Account ihres Planungsraums aus `assignment_plr.csv` und eine neue `lfd_nr` hinter der höchsten. Sie wird in `assignment.csv` aufgenommen (`aufgenommen` = Datum des Laufs). **Danach `assignment.csv` committen**, sonst vergibt der nächste Lauf die Nummer an einer anderen Stelle neu.
3. **Entfallene Kanten.** Zeilen von `assignment.csv`, deren Kante nicht mehr im Netz ist, fehlen in der Ausgabe; ihre Nummer wird nicht wieder vergeben. Hatten sie eine Markierung, meldet das Log das.
4. **Bearbeitungsstand** aus dem Editor übertragen, siehe [`bearbeitungsstand/`](../bearbeitungsstand/README.md).

Die `lfd_nr` der Zuteilung ist damit eine eigene Nummer. Sie ist anfangs gleich der `lfd_nr` des REN+-Netzes vom 2026-10-26, weicht aber ab, sobald `ren-network/unify_networks.py` das Netz neu nummeriert (dort ist `lfd_nr` nur eine laufende Nummer nach `element_nr`).

Danach die drei Datensätze in `tilda-static-data` hochladen (`infravelo-ren-netz-zuteilung`) und das Datum des Bearbeitungsstands in deren `description` eintragen.

## Zuteilung (eingecheckt)

| Datei | Inhalt |
|---|---|
| `assignment.csv` | je Kante `lfd_nr`, `element_nr`, `account`, `plr_id`, `aufgenommen`; für Kanten ohne `element_nr` zusätzlich Anfangs- und Endpunkt (`anfang_x` … `ende_y`, EPSG:25833) |
| `assignment_plr.csv` | je LOR-Planungsraum der `account`; die Gebiete sind die PLR eines Accounts in einem Bezirk |

Bezirk, Name des Planungsraums und `reihenfolge` einer Kante ergeben sich aus ihrer `plr_id` und den LOR-Daten, die Gebiete aus `assignment_plr.csv`.

Angelegt aus den Datensätzen „Zuteilung Netz“ und „Zuteilung Gebiete“ auf tilda-geo.de (Upload vom 2026-10-26, 5 Accounts, 12.062 Kanten, 60 Gebiete). Das ist der Stand, auf den die Mapper ihre Markierungen gesetzt haben.

## Ersterfassung (abgeschlossen)

`assign_accounts.py` hat die Gebiete geschnitten: Jede Kante gehört über ihren Mittelpunkt zu einem LOR-Planungsraum (PLR). Pro Bezirk wachsen von weit auseinander liegenden Startpunkten Gebiete über benachbarte PLR; danach wechseln PLR an den Gebietsgrenzen, solange das die Kilometer ausgleicht. Die Bezirke sind ab Neukölln gegen den Uhrzeigersinn nummeriert (`reihenfolge`). Gleiche Eingangsdaten und gleiche `accounts.txt` ergeben dieselbe Zuteilung. Optionen: `--start-district`, `--simplify`, `--reassign` (überschreibt `assignment.csv` und `assignment_plr.csv`; verschiebt Gebiete und Nummern).

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `assignment.csv`, `assignment_plr.csv` | Zuteilung, siehe oben |
| `data/ren_netz_gesamt.gpkg` | Vereinheitlichtes REN+-Netz (Layer `ren_netz`), Symlink; verteilt wird nur das Kartierungs-Netz (`bearbeitet_2025` nicht `ja`) |
| `data/lor_plr_2021.geojson` | [LOR-Planungsräume 2021](https://gdi.berlin.de/services/wfs/lor_2021), Layer `a_lor_plr_2021`; im Update für Bezirk, Planungsraum neuer Kanten und Gebiete |
| `accounts.txt` | Ein Account pro Zeile; nur für die Ersterfassung |

`data/` ist nicht versioniert.

## Ausgabe

In `output/` (nicht versioniert):

| Datei | Inhalt |
|---|---|
| `zuteilung_netz.geojson` | Netzkanten mit `lfd_nr`, `reihenfolge`, `bezirk`, `plr_id`, `plr_name`, `account`, `bearbeitungsstand`, `erledigt_von`, `erledigt_am`, `editor_markdown` |
| `zuteilung_gebiete.geojson` | Ein Gebiet je Bezirk und Account mit der Statistik als Attribute, `km_erledigt`, `erledigt_prozent` und `editor_markdown` |
| `zuteilung_statistik.csv` | Je Bezirk und Account: Kilometer, Kanten, PLR, Kilometer je Netzklasse und an Hauptverkehrsstraßen, erledigte Kilometer, Abweichung vom Bezirksmittel |

`editor_markdown` ist ein Link in den Mapping-Editor (`EDITOR_URL` in `assignment_output.py`). Er öffnet die Karte an der Kante bzw. im Gebiet und zeigt die Maske des Kartierungsnetzes und die Zuteilung, gefiltert auf den Account des Features.
