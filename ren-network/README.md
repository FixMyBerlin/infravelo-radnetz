# REN+

`unify_networks.py` führt die Netzquellen zu einem einheitlichen Netz für REN+ zusammen (Zustand vor dem Matching).

```bash
python ren-network/unify_networks.py
```

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `data/netzquellen/radverkehrsnetz.gpkg` | Radvorrang- und Ergänzungsnetz |
| `data/netzquellen/radschnellverbindungen.gpkg` | Radschnellverbindungen |
| `data/netzquellen/hauptstrassennetz.gpkg` | Hauptstraßennetz |
| `data/Berlin Straßenabschnitte Detailnetz.fgb` | Straßenname, Straßenklasse, Knotenpunkt-IDs |
| `data/Berlin Verbindungspunkte Detailnetz.fgb` | Knotenpunkte für die Berechnung fehlender `element_nr` |
| `data/Berlin Bezirke.gpkg` | Bezirksnummer |

Noch nicht enthalten: Touristisches Radnetz (Radfernwege), da ohne `element_nr` und Netzknoten.

## Ablauf

1. **Laden** der drei Netze in ein gemeinsames Schema (EPSG:25833).
2. **Fehlende `element_nr` berechnen** (`processing/scripts/assign_element_nr_to_rvn.py`): Knotenpunkte (Verbindungspunkte mit ID über `processing/scripts/assign_node_ids.py`) an den Kantenenden suchen, ohne Knotenpunkt entlang verbundener Kanten derselben Quelle weitersuchen. Verbindet das Detailnetz dieselben Knoten, wird dessen `element_nr` übernommen (richtungsunabhängig, bei mehreren die geometrisch nächste), sonst `von_bis.01`. Ohne Knotenpunkt an beiden Enden bleibt die Kante ohne `element_nr`.
3. **Zusammenführen** zu einer Kante pro `element_nr`. Geometrie aus der Quelle mit höchster Priorität (Radverkehrsnetz > Radschnellverbindungen > Hauptstraßennetz), `radverkehrsnetz` nach höchstem Rang (Vorrang > Ergänzung). Kanten ohne `element_nr` bleiben einzeln.
4. **Detailnetz**: Straßenname und -klasse über `element_nr` ergänzen; Abweichungen zum Hauptstraßennetz werden geloggt.
5. **Netzknoten** `von_knoten`/`bis_knoten` aus der `element_nr` (`von_bis.NN`).
6. **Bezirk** nach größtem räumlichen Anteil.
7. **Abschluss**: Länge, Hauptverkehrsstraße (nur Hauptstraßennetz mit Klasse I–III), `lfd_nr`.

## Ausgabe

In `ren-network/output/`:

- `ren_netz_vereinheitlicht.gpkg` (Layer `ren_netz`)
- `element_nr_nicht_im_detailnetz.csv`: Kanten, deren `element_nr` im Detailnetz fehlt

## Attribute

Nummern nach Anhang "Attribut mit Ausprägungen".

| Nr. | Attribut | Spalte | Stand |
|---|---|---|---|
| 1 | lfd. Nr. | `lfd_nr` | ✓ |
| 2 | Element-Nummer | `element_nr` | ✓ |
| 3 | von Netzknoten | `von_knoten` | ✓ |
| 4 | bis Netzknoten | `bis_knoten` | ✓ |
| 5 | Länge | `laenge_m` | ✓ |
| 6 | Richtung | – | offen |
| 7 | Bezirksnummer | `bezirksnummer` | ✓ |
| 8 | Straßenname | `strassenname` | ✓ |
| 9 | Radverkehrsnetz | `radverkehrsnetz` | ✓ |
| 10 | Routen Fernradweg | `routen_fernradweg` | leer |
| 11 | Hauptverkehrsstraße | `hauptverkehrsstrasse` | ✓ |
| 12–24 | Radverkehrsführung, Oberfläche, Protektion, Zustand, Kommentar | – | nach Matching |

Zusätzlich: `netz_quellen` (beteiligte Quellen), `in_detailnetz` (ja/nein), `element_nr_berechnet` (ja/nein).
