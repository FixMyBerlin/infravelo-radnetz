# Mapping-Zuteilung

`assign_accounts.py` teilt die Kanten des REN+-Netzes auf die Mapping-Accounts auf. Die Bezirke werden nacheinander bearbeitet; innerhalb eines Bezirks bekommt jeder Account ein zusammenhängendes Gebiet mit ähnlich vielen Netz-Kilometern, damit alle gleichzeitig arbeiten können.

```bash
python mapping-zuteilung/assign_accounts.py
```

Optionen: `--start-district` (Standard: Neukölln), `--simplify` (Toleranz der Vereinfachung, Standard 1 m).

Ändert sich die Account-Liste, `accounts.txt` anpassen und das Skript neu ausführen. Gleiche Eingangsdaten und gleiche Liste ergeben dieselbe Zuteilung.

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `accounts.txt` | Ein Account pro Zeile |
| `data/ren_netz_vereinheitlicht.gpkg` | Vereinheitlichtes REN+-Netz (Layer `ren_netz`), Symlink |
| `data/lor_plr_2021.geojson` | [LOR-Planungsräume 2021](https://gdi.berlin.de/services/wfs/lor_2021), Layer `a_lor_plr_2021` |

`data/` ist nicht versioniert.

## Ablauf

1. **LOR zuordnen.** Jede Kante gehört über ihren Mittelpunkt zu genau einem Planungsraum (PLR) und damit zu einem Bezirk.
2. **Gebiete bilden.** Pro Bezirk wachsen von weit auseinander liegenden Startpunkten Gebiete über benachbarte PLR. Danach wechseln PLR an den Gebietsgrenzen das Gebiet, solange das die Kilometer ausgleicht und die Gebiete zusammenhängend bleiben. Aus mehreren Startpunkt-Varianten wird die ausgeglichenste gewählt.
3. **Reihenfolge.** Die Bezirke sind ab dem Startbezirk gegen den Uhrzeigersinn nummeriert.

## Ausgabe

In `output/` (nicht versioniert):

| Datei | Inhalt |
|---|---|
| `zuteilung_netz.geojson` | Netzkanten mit `reihenfolge`, `bezirk`, `plr_id`, `plr_name`, `account` |
| `zuteilung_gebiete.geojson` | Ein Gebiet je Bezirk und Account mit der Statistik als Attribute |
| `zuteilung_statistik.csv` | Je Bezirk und Account: Kilometer, Kanten, PLR, Kilometer je Netzklasse und an Hauptverkehrsstraßen, Abweichung vom Bezirksmittel |
