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

- `netzanpassungen_<gebiet>.json`: Schema `netzanpassungen-app/v1`, WGS84 mit 7 Nachkommastellen, sechs FeatureCollections:
  - `detailnetz`: `element_nr`, `beginnt_bei_vp`, `endet_bei_vp`, `strassenname`, `verkehrsebene`, `okstra_id`
  - `knoten`: `id`, `ist_virtuell`. Die Detailnetzknoten kommen aus den Kantenenden: erster Punkt = `beginnt_bei_vp`, letzter = `endet_bei_vp`. Die Verbindungspunkte aus dem WFS haben keine Knoten-ID.
  - `ren_netz`: `element_nr`, `von_knoten`, `bis_knoten` (als Text), `radverkehrsnetz`, `strassenname`. MultiLineStrings sind in Teile zerlegt.
  - `radfernwege`: `name`
  - `luecken`: Abschnitte der Radfernwege, die weiter als 10 m von jeder Detailnetz- und REN+-Kante liegen, mindestens 20 m lang (Arbeitsliste der App)
  - `knoten_vorschlaege` (Test): Punkte, an denen ein Radfernweg eine Detailnetzkante kreuzt, mindestens 15 m von jedem Knoten entfernt (Kreuzungen auf derselben Kante unter 10 m werden zusammengelegt). Felder: `element_nr`, `strassenname`, `verkehrsebene`, `routen`, `winkel_grad`, `steil` (Schnittwinkel ab 30°; flachere Kreuzungen sind meist nur ein Radfernweg, der neben der Kante herläuft), `luecke_nah` (Anfang oder Ende einer Lücke innerhalb 25 m), `station_m`, `abstand_ende_m`. Stand 2026-10-23: 592 Vorschläge, 107 steil, 81 davon mit Lücke in der Nähe.
- `pruefliste_<gebiet>.csv`: Kantenenden, die mehr als 0,5 m neben ihrem Knoten liegen (Stand 2026-10-23: eins)

Mit `--bezirk` bleiben Kanten, Knoten und Radfernwege bis 200 m über die Bezirksgrenze hinaus enthalten; die Lücken werden vorher für ganz Berlin berechnet.

## Noch offen

Die Ergebnisse der App zurück in die Pipeline: virtuelle Knoten an `data/Virtuelle-Knotenpunkte.gpkg` anhängen, neue Kanten als Netzquelle in `unify_networks.py` (dort `von_knoten`/`bis_knoten` als Text, weil virtuelle IDs mit `V` beginnen), `routen_fernradweg` füllen.
