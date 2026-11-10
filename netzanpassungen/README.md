# Netzanpassungen

`export_app_daten.py` schreibt die Eingabedatei der App „Netzanpassungen“ (Repo [knotenpunkte](https://github.com/FixMyBerlin/knotenpunkte), Ordner `netzanpassungen/`). In der App werden entlang der Radfernwege neue Kanten gezeichnet, wo weder das Detailnetz noch das REN+ eine Kante hat. Dabei entstehen virtuelle Knoten auf vorhandenen Kanten. Außerdem werden REN+-Kanten korrigiert (Geometrie, Fahrbahnart, Verkehrsrichtung, Ausschluss). `import_app_export.py` bringt den Export der App zurück in die Pipeline.

```bash
python ren-network/unify_networks.py                  # nur bei geändertem REN+
python netzanpassungen/export_app_daten.py            # ganz Berlin
python netzanpassungen/export_app_daten.py --bezirk Neukölln
python netzanpassungen/import_app_export.py <export-alle-eintraege>.json   # Export der App zurück
python netzanpassungen/test_import_app_export.py                           # Selbsttest des Imports
```

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `data/Berlin Straßenabschnitte Detailnetz*.fgb` | Detailnetzkanten, jüngster Stand wie in `unify_networks.py` |
| `data/Virtuelle-Knotenpunkte.gpkg` | Virtuelle Knoten im Bestand |
| `ren-network/output/ren_netz_gesamt.gpkg` | REN+ gesamt, Original ohne Korrekturen (die Quelle der Korrekturen in der App) |
| `data/netzquellen/touristisches_radnetz.gpkg` | Radfernwege (8 Routen), aus dem Drive (`data/download_inputs.py`, läuft zu Beginn des Exports) |
| `data/Berlin Bezirke.gpkg` | nur mit `--bezirk` |

## Ausgabe

In `netzanpassungen/output/` (nicht versioniert):

- `netzanpassungen_<gebiet>.json`: Schema `netzanpassungen-app/v1`, WGS84 mit 7 Nachkommastellen, sechs FeatureCollections:
  - `detailnetz`: `element_nr`, `beginnt_bei_vp`, `endet_bei_vp`, `strassenname`, `verkehrsebene`, `okstra_id`
  - `knoten`: `id`, `ist_virtuell`. Die Detailnetzknoten kommen aus den Kantenenden: erster Punkt = `beginnt_bei_vp`, letzter = `endet_bei_vp`. Die Verbindungspunkte aus dem WFS haben keine Knoten-ID.
  - `ren_netz`: `element_nr`, `von_knoten`, `bis_knoten` (als Text), `radverkehrsnetz`, `strassenname`, `verkehrsrichtung` (B beide Richtungen, R nur in Linienrichtung, G nur dagegen; aus dem Detailnetz per `element_nr`, leer wenn dort keine Kante). MultiLineStrings sind in Teile zerlegt; die Linien tragen in der App den Schlüssel `element_nr`, ab der zweiten Linie derselben Nummer `#2`, ... (`kante.ref` der Korrekturen). Die Datei ist das ganze REN+ (`ren_netz_gesamt.gpkg`), nicht nur das Kartierungs-Netz.
  - `radfernwege`: `name`
  - `luecken`: Abschnitte der Radfernwege, die weiter als 10 m von jeder Detailnetz- und REN+-Kante liegen, mindestens 20 m lang (Arbeitsliste der App)
  - `knoten_vorschlaege` (Test): Punkte, an denen ein Radfernweg eine Detailnetzkante kreuzt, mindestens 15 m von jedem Knoten entfernt (Kreuzungen auf derselben Kante unter 10 m werden zusammengelegt). Felder: `element_nr`, `strassenname`, `verkehrsebene`, `routen`, `winkel_grad`, `steil` (Schnittwinkel ab 30°; flachere Kreuzungen sind meist nur ein Radfernweg, der neben der Kante herläuft), `luecke_nah` (Anfang oder Ende einer Lücke innerhalb 25 m), `station_m`, `abstand_ende_m`. Stand 2026-10-23: 592 Vorschläge, 107 steil, 81 davon mit Lücke in der Nähe.
- Kopf `ren_netz_stand`: `datei`, `datum` und `sha256` von `ren_netz_gesamt.gpkg`, auf dem die Korrekturen der App beruhen.
- `pruefliste_<gebiet>.csv`: Kantenenden, die mehr als 0,5 m neben ihrem Knoten liegen (Stand 2026-10-23: eins)

Mit `--bezirk` bleiben Kanten, Knoten und Radfernwege bis 200 m über die Bezirksgrenze hinaus enthalten; die Lücken werden vorher für ganz Berlin berechnet.

## Export der App zurück in die Pipeline

`import_app_export.py` liest den Export „alle Einträge“ der App (`{gebiet, exported_at, entries}`; Einträge mit `geloescht` werden übersprungen) und schreibt:

- `ren-network/output/ren_netz_gesamt_korrigiert.gpkg`, `ren_netz_kartierung_korrigiert.gpkg` / `.geojson` und `korrekturen_konflikte.csv` aus den `edge_correction`-Einträgen. Aufbau, Prüfungen (5 cm gegen `original_coordinates`, Wiederholung des Protokolls) und Spalten stehen in [`ren-network/README.md`](../ren-network/README.md#korrigiertes-netz).
- virtuelle Knoten in `data/Virtuelle-Knotenpunkte.gpkg` (nur neue IDs; eine ID, die dort an anderer Stelle liegt, kommt in die Konfliktliste), gezeichnete Kanten in `data/netzquellen/touristische_kanten.gpkg` (Layer `touristische_kanten`: `entry_id`, `element_nr`, `von_knoten`, `bis_knoten` als Text, `quelle`, `strassenname`, `routen_fernradweg`, `kommentar`). Die `element_nr` zählt wie in der App (`von_bis.NN`, in der Reihenfolge des Zeichnens, nach Detailnetz und REN+); das Teilen an virtuellen Knoten übernimmt `processing/scripts/split_rvn_at_virtual_nodes.py`. Gelöschte virtuelle Knoten werden nicht aus der Datei entfernt.

Achtung Kartierung: Das Original `ren_netz_kartierung.gpkg` / `.geojson` enthält seit der Entfernung der Ausschlussliste wieder die 19 Ausschluss-Kanten (Tunnel Tiergarten, Zubringer); nur `ren_netz_kartierung_korrigiert` lässt sie weg. Der TILDA-Datensatz `infravelo-ren-netz-kartierung` (Symlink in `tilda-static-data`, außerhalb dieses Repos) muss deshalb auf die `_korrigiert`-Datei zeigen.

Noch offen: `unify_networks.py` liest `touristische_kanten.gpkg` nicht als Netzquelle (`von_knoten`/`bis_knoten` als Text, weil virtuelle IDs mit `V` beginnen; `routen_fernradweg` füllen).

## Altlisten

`output/altlisten_korrekturen.json` (versioniert) enthält die Altlisten als `edge_correction`-Einträge (`von_nutzer: "Altliste"`) zum Einspielen in der App („Korrekturen einspielen“): `verkehrsrichtung` aus `rvn_korrekturen.csv` und `opposite_edge_overwrite_element_nr.txt` (Modus `remove`, nur Kanten mit Detailnetz-`verkehrsrichtung` B, neu R) sowie die Ausschlüsse aus `ausschluss_element_nr.csv`. Die drei Listen und der Code, der sie las, sind entfernt (darunter `processing/helpers/override_edges.py`, `processing/validation/analyse_einrichtungsfahrbahnen.py` und `processing/qgis/erzeuge_einrichtungsfahrbahnen_projekt.py`); erzeugt hat die Datei ein einmaliges Skript, das nicht im Repo liegt (Stand 2026-11-10).

## QGIS-Stil

`netz-aenderungen.qml` stylt den GeoJSON-Export `netz-aenderungen` der App nach `darstellung`: `alt` grau gestrichelt, `neu` blau, `differenz` rot halbtransparent, `vektor` roter Pfeil von alt nach neu mit `abstand_m` als Beschriftung, `attribut` orange, `gruppe` grün dünn gestrichelt. Der Export enthält Linien und Flächen; QGIS legt dafür zwei Layer an, auf beide den Stil laden (Layer-Eigenschaften, Symbolisierung, Stil, Stil laden).
