# Netzanpassungen

`export_app_daten.py` schreibt die Eingabedatei der App „Netzanpassungen“ (Repo [knotenpunkte](https://github.com/FixMyBerlin/knotenpunkte), Ordner `netzanpassungen/`). In der App werden entlang der Radfernwege neue Kanten gezeichnet, wo weder das Detailnetz noch das REN+ eine Kante hat. Dabei entstehen virtuelle Knoten auf vorhandenen Kanten.

```bash
python ren-network/unify_networks.py                  # nur bei geändertem REN+
python netzanpassungen/export_app_daten.py            # ganz Berlin
python netzanpassungen/export_app_daten.py --bezirk Neukölln
```

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `data/Berlin Straßenabschnitte Detailnetz*.fgb` | Detailnetzkanten, jüngster Stand wie in `unify_networks.py` |
| `data/Virtuelle-Knotenpunkte.gpkg` | Virtuelle Knoten im Bestand |
| `ren-network/output/ren_netz_kartierung.gpkg` | REN+-Kartierungs-Netz |
| `data/netzquellen/touristisches_radnetz.gpkg` | Radfernwege (8 Routen) |
| `data/Berlin Bezirke.gpkg` | nur mit `--bezirk` |

## Ausgabe

In `netzanpassungen/output/` (nicht versioniert):

- `netzanpassungen_<gebiet>.json`: Schema `netzanpassungen-app/v1`, WGS84 mit 7 Nachkommastellen, fünf FeatureCollections:
  - `detailnetz`: `element_nr`, `beginnt_bei_vp`, `endet_bei_vp`, `strassenname`, `verkehrsebene`, `okstra_id`
  - `knoten`: `id`, `ist_virtuell`. Die Detailnetzknoten kommen aus den Kantenenden: erster Punkt = `beginnt_bei_vp`, letzter = `endet_bei_vp`. Die Verbindungspunkte aus dem WFS haben keine Knoten-ID.
  - `ren_netz`: `element_nr`, `von_knoten`, `bis_knoten` (als Text), `radverkehrsnetz`, `strassenname`. MultiLineStrings sind in Teile zerlegt.
  - `radfernwege`: `name`
  - `luecken`: Abschnitte der Radfernwege, die weiter als 10 m von jeder Detailnetz- und REN+-Kante liegen, mindestens 20 m lang (Arbeitsliste der App)
- `pruefliste_<gebiet>.csv`: Kantenenden, die mehr als 0,5 m neben ihrem Knoten liegen (Stand 2026-10-23: eins)

Mit `--bezirk` bleiben Kanten, Knoten und Radfernwege bis 200 m über die Bezirksgrenze hinaus enthalten; die Lücken werden vorher für ganz Berlin berechnet.

## Noch offen

Die Ergebnisse der App zurück in die Pipeline: virtuelle Knoten an `data/Virtuelle-Knotenpunkte.gpkg` anhängen, neue Kanten als Netzquelle in `unify_networks.py` (dort `von_knoten`/`bis_knoten` als Text, weil virtuelle IDs mit `V` beginnen), `routen_fernradweg` füllen.
