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
| `data/Berlin Straßenabschnitte Detailnetz.fgb` | Straßenname, Straßenklasse, Autobahn-Kennung, Knotenpunkt-IDs |
| `data/Berlin Verbindungspunkte Detailnetz.fgb` | Knotenpunkte für die Berechnung fehlender `element_nr` |
| `data/Berlin Bezirke.gpkg` | Bezirksnummer |

Die Dateien in `data/netzquellen/` und die Verbindungspunkte sind nicht versioniert. Liegt neben dem versionierten Detailnetz ein neuerer Stand mit Datum im Namen (`Berlin Straßenabschnitte Detailnetz <Datum>.fgb`, ebenfalls nicht versioniert), wird der jüngste verwendet. Beide Detailnetz-Layer kommen aus dem [WFS Detailnetz Berlin](https://daten.berlin.de/datensaetze/detailnetz-berlin-wfs-4f2045ef):

```bash
cd data
ogr2ogr -f FlatGeobuf "Berlin Verbindungspunkte Detailnetz.fgb" "WFS:https://gdi.berlin.de/services/wfs/detailnetz" "detailnetz:a_verbindungspunkte"
ogr2ogr -f FlatGeobuf -nlt MULTILINESTRING "Berlin Straßenabschnitte Detailnetz $(date +%F).fgb" "WFS:https://gdi.berlin.de/services/wfs/detailnetz" "detailnetz:c_strassenabschnitte"
```

Noch nicht enthalten: Touristisches Radnetz (Radfernwege), da ohne `element_nr` und Netzknoten.

## Ablauf

1. **Laden** der drei Netze in ein gemeinsames Schema (EPSG:25833).
2. **Autobahnen entfernen**: Kanten des Hauptstraßennetzes, die im Detailnetz als Autobahn geführt sind (`strassenklasse2` = `AUBA` oder `AUTO`, inkl. Zubringer und Anschlussstellen), entfallen. Gehört dieselbe Kante auch zum Radverkehrsnetz oder zu einer Radschnellverbindung, bleibt sie über diese Quelle erhalten und wird im Log aufgelistet.
3. **Ausschlussliste**: Kanten aus [`ausschluss_element_nr.csv`](./ausschluss_element_nr.csv) (`element_nr`, `grund`, `strassenname`) entfallen aus allen Quellen. Dort stehen Kanten, die die Autobahn-Regel nicht erfasst, z. B. der Tunnel Tiergarten.
4. **Fehlende `element_nr` berechnen** (`processing/scripts/assign_element_nr_to_rvn.py`): Knotenpunkte (Verbindungspunkte mit ID über `processing/scripts/assign_node_ids.py`) an den Kantenenden suchen, ohne Knotenpunkt entlang verbundener Kanten derselben Quelle weitersuchen. Verbindet das Detailnetz dieselben Knoten, wird dessen `element_nr` übernommen (richtungsunabhängig, bei mehreren die geometrisch nächste), sonst `von_bis.01`. Ohne Knotenpunkt an beiden Enden bleibt die Kante ohne `element_nr`.
5. **Zusammenführen** zu einer Kante pro `element_nr`. Geometrie aus der Quelle mit höchster Priorität (Radverkehrsnetz > Radschnellverbindungen > Hauptstraßennetz), die die Kante vollständig abdeckt: Ist eine vorrangige Quelle mehr als 10 m kürzer als eine andere, gewinnt die längere. `radverkehrsnetz` nach höchstem Rang (Vorrang > Ergänzung). Kanten ohne `element_nr` bleiben einzeln.
6. **Detailnetz**: Straßenname und -klasse über `element_nr` ergänzen; Abweichungen zum Hauptstraßennetz werden geloggt.
7. **Netzknoten** `von_knoten`/`bis_knoten` aus der `element_nr` (`von_bis.NN`).
8. **Bezirk** nach größtem räumlichen Anteil.
9. **Abschluss**: Länge, Hauptverkehrsstraße (nur Hauptstraßennetz mit Klasse I–III), `lfd_nr`.

## Ausgabe

In `ren-network/output/`:

- `ren_netz_vereinheitlicht.gpkg` (Layer `ren_netz`)
- `ren_netz_vereinheitlicht.geojson`: dasselbe Netz in WGS84, z. B. für [play.placemark.io](https://play.placemark.io)
- `element_nr_nicht_im_detailnetz.csv`: Kanten, deren `element_nr` im Detailnetz fehlt

## Maskierung

`create_mask.py` erzeugt die Maskierung für die Karte: die Fläche Berlins ohne einen 25-m-Puffer um das Netz, auf 7 m vereinfacht. Sie entspricht der Maskierung des Radvorrangnetzes von 2025 in `tilda-static-data` (`region-berlin/radverkehrsnetz-vorrangnetz-mask`), die damals in QGIS entstand.

```bash
python ren-network/create_mask.py
```

Ausgabe: `ren-network/output/ren_netz_maske.geojson` (WGS84, ein MultiPolygon). Nach jeder Änderung am Netz neu erzeugen.

## Prüfliste doppelter Kanten

`audit_double_edges.py` sucht Kanten, die denselben Weg doppelt abbilden. Es entfernt nichts; was nach der Prüfung wegfallen soll, kommt in `ausschluss_element_nr.csv`.

```bash
python ren-network/audit_double_edges.py
```

| `typ` | Bedeutung |
|---|---|
| `ueberlappend` | Zwei Kanten liegen aufeinander: mindestens 50 % der einen im Abstand von 3 m zur anderen |
| `parallel_zum_radverkehrsnetz` | Eine Kante ohne Radverkehrsnetz verläuft zu mindestens 80 % im Abstand von 20 m neben Kanten des Radverkehrsnetzes |

Ausgabe in `ren-network/output/`: `doppelte_kanten.csv` (eine Zeile je Fund mit Kandidat, Partnerkanten, Anteil, `gleiches_knotenpaar`) und `doppelte_kanten.geojson` (Kandidaten und Partner mit Fundnummer `nr` und `rolle`).

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

Zusätzlich: `strassenklasse` (Straßenstufe 0–V aus Hauptstraßennetz bzw. Detailnetz), `netz_quellen` (beteiligte Quellen), `netz_quellen_teilweise` (Quellen, die nur einen Teil der Kante abdecken; `radverkehrsnetz` gilt dann nicht für die ganze Kante), `in_detailnetz` (ja/nein), `element_nr_berechnet` (ja/nein).
