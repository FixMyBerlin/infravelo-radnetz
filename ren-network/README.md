# REN+

`merge_networks.py` ist **Schritt 1** der Pipeline (bisher `unify_networks.py`, Gesamtbild: [`docs/network-pipeline.md`](../docs/network-pipeline.md)): Es führt die Netzquellen zu einem einheitlichen **Rohnetz** für REN+ zusammen (`ren_netz_roh.gpkg`), reine Rohdaten ohne Bezug zur App Netzanpassungen oder zu den Radfernwegen. Danach folgen:

| Schritt | Skript | Ergebnis |
|---|---|---|
| 1 | `ren-network/merge_networks.py` | `ren_netz_roh.gpkg` |
| 2 | `netzanpassungen/match_cycle_routes.py` | `netzanpassungen/output/ren_netz_auto.gpkg`, `radfernweg_abschnitte.gpkg` |
| – | `netzanpassungen/write_app_input.py` | `netzanpassungen/output/netzanpassungen_<gebiet>.json` für die App |
| 3 | `netzanpassungen/apply_app_result.py` | `ren_netz.gpkg` (Kunde), `ren_netz_korrigiert.gpkg` (Matching, Mapping), jeweils mit Kartierung |

Das ganze Netz, das der Kunde bekommt, ist `ren_netz.gpkg`; mit Lagekorrekturen daneben `ren_netz_korrigiert.gpkg` (siehe [Ergebnisnetze](#ergebnisnetze-schritt-3)). Die Kartierung (ohne die 2025 schon gelieferten Kanten, siehe [Lieferung 2025](#lieferung-2025)) schreibt Schritt 3 für beide.

```bash
python ren-network/merge_networks.py
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
| `../tilda-static-data/geojson/region-infravelo/infravelo-datensatz-c-fortlaufend/aggregated_rvn_final.geojson.gz` | Ergebnis der Bearbeitung 2025 (Radvorrangnetz). Lebt nur in `tilda-static-data`, das als Schwesterordner ausgecheckt sein muss |

Die Dateien in `data/netzquellen/` und die Verbindungspunkte sind nicht versioniert. Liegt neben dem versionierten Detailnetz ein neuerer Stand mit Datum im Namen (`Berlin Straßenabschnitte Detailnetz <Datum>.fgb`, ebenfalls nicht versioniert), wird der jüngste verwendet. Beide Detailnetz-Layer kommen aus dem [WFS Detailnetz Berlin](https://daten.berlin.de/datensaetze/detailnetz-berlin-wfs-4f2045ef):

```bash
cd data
ogr2ogr -f FlatGeobuf "Berlin Verbindungspunkte Detailnetz.fgb" "WFS:https://gdi.berlin.de/services/wfs/detailnetz" "detailnetz:a_verbindungspunkte"
ogr2ogr -f FlatGeobuf -nlt MULTILINESTRING "Berlin Straßenabschnitte Detailnetz $(date +%F).fgb" "WFS:https://gdi.berlin.de/services/wfs/detailnetz" "detailnetz:c_strassenabschnitte"
```

Das Touristische Radnetz (Radfernwege) hat weder `element_nr` noch Netzknoten und kommt erst in Schritt 2 dazu (`netzanpassungen/match_cycle_routes.py`); `routen_fernradweg` ist hier noch leer.

## Ablauf

1. **Laden** der drei Netze in ein gemeinsames Schema (EPSG:25833).
2. **Autobahnen entfernen**: Kanten des Hauptstraßennetzes, die im Detailnetz als Autobahn geführt sind (`strassenklasse2` = `AUBA` oder `AUTO`, inkl. Zubringer und Anschlussstellen), entfallen. Gehört dieselbe Kante auch zum Radverkehrsnetz oder zu einer Radschnellverbindung, bleibt sie über diese Quelle erhalten und wird im Log aufgelistet.
3. Einzelne Kanten, die die Autobahn-Regel nicht erfasst (z. B. der Tunnel Tiergarten), bleiben im Rohnetz. Sie werden in der App Netzanpassungen ausgeschlossen, in `ren_netz.gpkg` und `ren_netz_korrigiert.gpkg` sind sie als `ausgeschlossen` markiert, die Kartierung lässt sie weg (bis 2026-11-10 stand dafür die Liste `ausschluss_element_nr.csv`; ihre 19 Kanten wurden in `netzanpassungen/one_time_import/altlisten_korrekturen.json` übertragen; gelöscht sind außerdem `data/rvn_korrekturen.csv`, `data/opposite_edge_overwrite_element_nr.txt` und der Code, der die Listen las, darunter `processing/qgis/erzeuge_einrichtungsfahrbahnen_projekt.py`).
4. **Fehlende `element_nr` berechnen** (the function `assign_element_numbers` from `processing/scripts/assign_element_nr_to_rvn.py`, imported by `merge_networks.py`; the script itself is not part of step 1): Knotenpunkte (Verbindungspunkte mit ID über `processing/scripts/assign_node_ids.py`) an den Kantenenden suchen, ohne Knotenpunkt entlang verbundener Kanten derselben Quelle weitersuchen. Verbindet das Detailnetz dieselben Knoten, wird dessen `element_nr` übernommen (richtungsunabhängig, bei mehreren die geometrisch nächste), sonst `von_bis.01`. Ohne Knotenpunkt an beiden Enden bleibt die Kante ohne `element_nr`.
5. **Zusammenführen** zu einer Kante pro `element_nr`. Geometrie aus der Quelle mit höchster Priorität (Radverkehrsnetz > Radschnellverbindungen > Hauptstraßennetz), die die Kante vollständig abdeckt: Ist eine vorrangige Quelle mehr als 10 m kürzer als eine andere, gewinnt die längere. `radverkehrsnetz` nach höchstem Rang (Vorrang > Ergänzung). Kanten ohne `element_nr` bleiben einzeln.
6. **Detailnetz**: Straßenname und -klasse über `element_nr` ergänzen; Abweichungen zum Hauptstraßennetz werden geloggt.
7. **Virtual nodes and unique `element_nr`** (`ren-network/auto_nodes.py`, English since this step): every edge gets a unique `element_nr` `<von>_<bis>.<nn>` built from its two end nodes (`nn` counts per unordered node pair above the REN+ and Detailnetz numbers). End nodes are the Detailnetz nodes (end within 3 m), the 53 virtual nodes of 2025 (`data/virtuelle_knoten_2025.gpkg`, fixed names, read-only input) and automatic virtual nodes set by snapping (tolerance 2 m, chosen from the data: 606 of 633 loose ends touch another edge exactly, 621 within 2 m):
   - **on an edge**: an edge end lies on the interior of another REN+ edge; a node is set there, the other edge is split. A 2025 node within 2 m of such a point is that node and supplies the name; every 2025 node also splits the edges passing through it.
   - **junction**: edge ends that meet with no official node and no edge passing through share one node.
   - **dead end**: an end that touches nothing gets an end node.
   Names like the app (`netzanpassungen/src/network/naming.ts`): `V<A>-<B>` with the nearest official nodes along the host, `-2`, `-3` on collision; junctions and dead ends `V<nearest official>-<n>`. An existing `element_nr` is never changed unless it has to be: an edge keeps it if it was not split (even if an end is off its node) and it is the longest line with that number. New numbers only for edges without one, the pieces of split edges (old number in `ursprung_element_nr`) and the extra lines of a duplicated number. Multi-part edges are split into separate edges (one LineString each). The step fails loudly if an `element_nr` is missing or occurs twice. `von_knoten`/`bis_knoten` are text (virtual names start with `V`).
8. **Bezirk** nach größtem räumlichen Anteil.
9. **Abgleich mit der Lieferung 2025** über die Geometrie (siehe [Lieferung 2025](#lieferung-2025)).
10. **Abschluss**: Länge, Hauptverkehrsstraße (nur Hauptstraßennetz mit Klasse I–III), `lfd_nr`.

## Ausgabe

In `ren-network/output/` schreibt Schritt 1:

- `ren_netz_roh.gpkg` (Layer `ren_netz`), bisher `ren_netz_gesamt.gpkg`
- `virtuelle_knoten_roh.gpkg` (Layer `Virtuelle-Knotenpunkte`): the virtual nodes of step 1, `quelle` = `2025` or `auto`, `art` = `on_edge` | `junction` | `dead_end`, host edge and station. Step 3 adds the nodes drawn in the app and writes `netzanpassungen/output/virtuelle_knoten.gpkg`; the app input carries them as `knoten` with `ist_virtuell = 1`.
- `ren_netz_roh.geojson`: dasselbe Netz in WGS84, z. B. für [play.placemark.io](https://play.placemark.io)
- `bearbeitet_2025_abweichungen.csv`: Prüfliste zum Abgleich mit der Lieferung 2025
- `element_nr_nicht_im_detailnetz.csv`: Kanten, deren `element_nr` im Detailnetz fehlt

Schritt 3 schreibt dorthin die Ergebnisnetze (siehe unten): `ren_netz.gpkg` / `.geojson`, `ren_netz_kartierung.gpkg` / `.geojson`, `ren_netz_korrigiert.gpkg` / `.geojson`, `ren_netz_kartierung_korrigiert.gpkg` / `.geojson`, `korrekturen_konflikte.csv`, `radfernweg_zuordnungen.csv`. `befahrungsbedarf/`, `maproulette-centerline-tracks/` und `mapping-zuteilung/` lesen `ren_netz.gpkg` und filtern die Kartierung selbst.

## Ergebnisnetze (Schritt 3)

In der App Netzanpassungen (Repo [knotenpunkte](https://github.com/FixMyBerlin/knotenpunkte), Ordner `netzanpassungen/`) werden die Radfernwege den Kanten zugeordnet und REN+-Kanten korrigiert: Stützpunkte verschieben oder einfügen, `fahrbahn_typ`, `fahrbahn_gruppe`, `verkehrsrichtung` setzen, Kanten ausschließen. `von_knoten`, `bis_knoten` und `element_nr` einer Kante ändern sich dabei nie. `apply_app_result.py` spielt den App-Export „alle Einträge“ auf `netzanpassungen/output/ren_netz_auto.gpkg` (Schritt 2) ab:

```bash
python netzanpassungen/apply_app_result.py netzanpassungen-alle-eintraege-berlin-2026-11-12.json
python netzanpassungen/apply_app_result.py --ohne-export    # nur Schritt 2, ohne Handarbeit
python netzanpassungen/test_apply_app_result.py             # Selbsttest
```

| Datei in `ren-network/output/` | Inhalt |
|---|---|
| `ren_netz.gpkg` / `.geojson` | **Kunde.** Rohnetz + Radfernwege (automatisch und von Hand) + aufgenommene Detailnetzkanten + Richtung, Fahrbahn, Ausschluss, alles aus der App markiert. Originallage, **keine** Lagekorrekturen |
| `ren_netz_korrigiert.gpkg` / `.geojson` | **Matching und Mapping.** Dieselben Kanten und Spalten, dazu die Lagekorrekturen: `lage_korrigiert` (ja/nein) und die Kennzahlen `hausdorff_m`, `max_verschiebung_m`, `differenzflaeche_m2`, `laenge_alt_m`, `laenge_neu_m` |
| `ren_netz_kartierung.gpkg`, `ren_netz_kartierung_korrigiert.gpkg` (je `.gpkg` und `.geojson`) | Kartierung der beiden Netze: ohne `bearbeitet_2025 = ja` (teilweise gelieferte Kanten bleiben) und ohne ausgeschlossene Kanten. Darauf bauen die Mapper |
| `korrekturen_konflikte.csv` | Korrekturen und Zuordnungen, die nicht angewendet wurden, mit Grund, und Hinweise zu Knoten und Kanten |
| `radfernweg_zuordnungen.csv` | Eine Zeile je Entscheidung zu einem Abschnitt (zugeordnet, keine_aktion, Konflikt) |

Spalten, die beide Netze zusätzlich zu denen von Schritt 1 tragen:

| Spalte | Inhalt |
|---|---|
| `quelle` | `radnetz`, `detailnetz_radfernweg` (in Schritt 2 automatisch aufgenommen), `detailnetz_manuell` (über eine Zuordnung in der App), `neu_gezeichnet` (in der App gezeichnete Kante) |
| `ursprung_element_nr` | bei Teilkanten (Teilung an einem virtuellen Knoten) die `element_nr` der geteilten Kante, sonst leer |
| `grund_aufnahme` | `radfernweg`, `radfernweg_manuell` oder leer |
| `routen_fernradweg`, `routen_quelle` | Routennamen (mehrere mit `; `); `auto`, `manuell` oder `auto; manuell` |
| `verkehrsrichtung`, `verkehrsrichtung_original`, `verkehrsrichtung_korrigiert` | B/R/G aus dem Detailnetz bzw. korrigiert; Wert vor der Korrektur; ja/nein |
| `fahrbahn_typ`, `fahrbahn_gruppe` | wie in der App erfasst, sonst leer |
| `ausgeschlossen`, `ausschluss_grund` | ja/nein; Kommentar der Korrektur. Ausgeschlossene Kanten bleiben in beiden Netzen, sind aber markiert |
| `eintrag_ids` | KV-Ids der Einträge, die diese Kante betreffen (`; `-getrennt) |
| `anzahl_vorgaenge`, `letzte_aenderung_am`, `letzte_aenderung_von`, `korrektur_kommentar` | Protokoll der Korrektur |

Eine Korrektur wird nur angewendet, wenn die Kante noch im Eingangsnetz liegt (Schlüssel `kante.ref`: `element_nr`, ab der zweiten Linie derselben Nummer `#2`), ihre `original_coordinates` höchstens 5 cm von der Geometrie dort abweichen und das Protokoll (`original_coordinates` + `aenderungen`) den gespeicherten Stand ergibt. Sonst bleibt die Kante unverändert und steht in `korrekturen_konflikte.csv`. Das passiert, wenn sich `ren_netz_auto.gpkg` seit dem Export an die App geändert hat. Zuordnungen zu Abschnitten der Radfernwege (`section_assignment`) und ihre Regeln: [`netzanpassungen/README.md`](../netzanpassungen/README.md).

Gezeichnete Kanten stehen in beiden Netzen, virtuelle Knoten teilen ihre Trägerkante (Details: `netzanpassungen/README.md`). Zusätzlich schreibt Schritt 3 beide nach `netzanpassungen/output/virtuelle_knoten.gpkg` und `netzanpassungen/output/touristische_kanten.gpkg` (bei jedem Lauf neu aus dem Export, nie nach `data/`).

**Was damit läuft.** Das Matching (`processing/process_radnetz.sh --netz ren`) nimmt standardmäßig das korrigierte Netz, solange `ren_netz_korrigiert.gpkg` existiert; `--quelle original` nimmt `ren_netz.gpkg`, `--quelle korrigiert` bricht ohne die Datei ab. Ausgeschlossene Kanten entfallen dabei, und die korrigierte `verkehrsrichtung` (`verkehrsrichtung_korrigiert = ja`) gilt statt der des Detailnetzes. Das Ergebnis liegt dann auf den korrigierten Linien.

**Kartierung in TILDA.** Der Datensatz `infravelo-ren-netz-kartierung` kommt per Symlink aus `tilda-static-data` (außerhalb dieses Repos). Der Symlink muss auf `ren_netz_kartierung_korrigiert.geojson` zeigen, sonst sehen die Mapper keine Lagekorrekturen. Der Symlink wird hier nicht geändert.

**Zurück aufs Original.** `map_back_to_original.py` legt das Matching-Ergebnis (`processing/output/map-matching-ren/network_enriched_hmm.fgb`) auf die Originallinien aus `ren_netz.gpkg`: Jedes Teilsegment wird auf seine korrigierte Kante projiziert, der Abschnitt dort gilt anteilig für die Originalkante (`von_m`, `bis_m`, `von_anteil`, `bis_anteil`). Geteilte Kanten (virtuelle Knoten) finden ihre Ursprungskante über `elem_nr` in `processing/output/ren/ren_netz_with_element_nr.fgb` (`ursprung_element_nr`). Segmente auf in der App gezeichneten Kanten gibt es im Original nicht; sie stehen in `<Ausgabe>_ohne_original.csv`.

```bash
python ren-network/map_back_to_original.py
python ren-network/test_map_back_to_original.py   # Selbsttest
```

## Lieferung 2025

Das Gesamtnetz enthält auch das Radvorrangnetz, das 2025 schon bearbeitet und an die infraVelo geliefert wurde. Kartiert wird 2026 nur, was damals nicht geliefert wurde. Dafür vergleicht `merge_networks.py` jede Kante mit der Lieferung (`bearbeitet_2025`); die Kartierungs-Netze filtert Schritt 3.

### Grundsätze

- **Maßgeblich ist die Lieferung**, also Datensatz C (`infravelo-datensatz-c-fortlaufend`, Stand 29.01.2026), nicht das heutige Radvorrangnetz des Geoportals.
- **Was geliefert wurde, entfällt** aus dem Kartierungs-Netz.
- **Was heute im Netz ist, aber nicht geliefert wurde, bleibt**, auch wenn es zum Radvorrangnetz gehört.
- **Was geliefert wurde, aber heute nicht mehr im Netz ist, fällt weg**: Es steht nicht im Gesamtnetz und wird von der neuen Prozessierung nicht mehr erzeugt.
- **Auch die Kanten von 2025 werden neu prozessiert.** Der Abgleich bestimmt nur, wo kartiert wird, nicht was geliefert wird.

### Warum über die Geometrie und nicht über die `element_nr`

Die erste Fassung (2026-10-07) markierte eine Kante als bearbeitet, wenn ihre `element_nr` in der Lieferung stand, und nur ersatzweise über die Geometrie. Das war an drei Stellen falsch:

1. **Die Stadt hat das Radvorrangnetz seit 2025 geändert.** Rund 4 km sind neu, rund 1 km ist entfallen. Beispiel Neukölln: 2025 lief das Netz über die Niemetzstraße, heute über Schudomastraße und Braunschweiger Straße. [Ansehen](https://tilda-geo.de/regionen/infravelo/hinweise?config=1wy5p9w.5ount0.6cgu&v=3&map=16.4/52.4727/13.4523&data=infravelo-ren-netz-kartierung,infravelo-datensatz-c-fortlaufend): Die Schudomastraße ist im Kartierungs-Netz, die Niemetzstraße nur in Datensatz C.
2. **Nummern liegen heute an anderer Stelle.** Bei 25 Kanten steht die `element_nr` in der Lieferung, die Geometrie von damals deckt die heutige Kante aber gar nicht oder nur zum Teil ab. Über die Nummer wären sie als bearbeitet entfallen, obwohl dort nie kartiert wurde. Beispiel [Clauertstraße](https://tilda-geo.de/regionen/infravelo/hinweise?config=1wy5p9w.5ount0.6cgu&v=3&map=16/52.4259/13.2355&data=infravelo-ren-netz-kartierung,infravelo-datensatz-c-fortlaufend) (`34450008_35440016.01`, 4 % Überdeckung).
3. **2025 waren Kanten an virtuellen Knotenpunkten geteilt** (Nummern mit `V…`), die es im heutigen Netz nicht gibt. Eine heutige Kante entspricht dann mehreren Kanten der Lieferung mit anderen Nummern. Beispiel [Kante 11636](https://tilda-geo.de/regionen/infravelo/hinweise?config=1wy5p9w.5ount0.6cgu&v=3&map=15.5/52.4831/13.4594&data=infravelo-ren-netz,infravelo-datensatz-c-fortlaufend) (`50490012_50510009.01`): 97 % geliefert, aber unter drei `V…`-Nummern.

### Regel

Eine Kante gilt als geliefert, soweit sie im 5-m-Puffer um die Kanten der Lieferung liegt.

| `bearbeitet_2025` | Bedingung | Im Kartierungs-Netz | Kanten (2026-10-08) |
|---|---|---|---|
| `ja` | mindestens 90 % geliefert und höchstens 100 m offen | nein | 5.230, 876 km |
| `teilweise` | mindestens 20 % und 30 m geliefert | ja, als ganze Kante | 44, 29 km |
| `nein` | weniger; kurze Überdeckungen sind Berührungen an Kreuzungen | ja | 11.999, 1.967 km |

Die Schwellen stehen als `RESULT_2025_…` oben in `merge_networks.py`.

### Teilweise gelieferte Kanten

**Kanten werden nicht geteilt.** Eine teilweise gelieferte Kante bleibt als Ganzes im Kartierungs-Netz, auch wenn ein Teil davon schon geliefert ist (zusammen rund 15 km). Teilen hieße, die virtuellen Knotenpunkte jetzt schon einzuführen; das soll erst später in der Prozessierung passieren. Bis dahin gilt: lieber eine längere Kante kartieren als einen nicht gelieferten Teil verlieren.

Beispiel [Kante 11601](https://tilda-geo.de/regionen/infravelo/hinweise?config=1wy5p9w.5ount0.6cgu&v=3&map=15/52.4576/13.4616&data=infravelo-ren-netz-kartierung,infravelo-datensatz-c-fortlaufend) (`50470016_51480029.01`, 2.651 m): Im Radverkehrsnetz des Geoportals sind das sechs Abschnitte ohne `elem_nr`, drei im Radvorrangnetz und drei im Ergänzungsnetz. Schritt 4 berechnet für alle dasselbe Knotenpaar, Schritt 5 führt sie zu einer Kante zusammen. Die drei Vorrang-Abschnitte (1.254 m, 47 %) wurden 2025 unter zwei `V…`-Nummern geliefert, die drei Ergänzungs-Abschnitte nicht. Die Kante ist deshalb `teilweise`. Zwei Folgen dieser Zusammenführung sind bekannt und bleiben vorerst so:

- `radverkehrsnetz` nennt den höchsten Rang (hier Radvorrangnetz), obwohl mehr als die Hälfte der Kante Ergänzungsnetz ist. Das betrifft 14 Kanten (rund 20 km).
- Die Kante ist ein MultiLineString aus mehreren Stücken.

### Spalten und Darstellung

- `anteil_2025`: gelieferter Anteil der Kante (0–1).
- `element_nr_2025`: Nummern der Kanten der Lieferung, die mindestens 30 m der Kante abdecken, die längste zuerst, durch Semikolon getrennt.
- `hinweis_2025`: ein erklärender Satz, wenn die Kante vom Normalfall abweicht. Drei Fälle: teilweise geliefert (mit Anteil, Metern und den Nummern von 2025), unter anderer Nummer geliefert (228 Kanten), oder die `element_nr` stand in der Lieferung, lag dort aber an anderer Stelle.

In TILDA zeigen „REN+ Gesamtnetz“ und „Netz“ (Kategorie „Netz: REN+ Kartierung“) Kanten mit Hinweis, die im Kartierungs-Netz bleiben, mit weiß gestrichelter Mittellinie. Der Hinweis steht beim Klick in den Attributen.

`bearbeitet_2025_abweichungen.csv` listet alle Kanten mit Hinweis, außerdem die 20 Kanten des heutigen Radvorrangnetzes ohne Lieferung und die 12 Nummern der Lieferung, die heute keine Kante mehr abdecken.

### Datensätze in TILDA

| Datensatz | Inhalt |
|---|---|
| „Datensatz C - Aggregiert“ | die Lieferung 2025 |
| „Radvorrangnetz 2025 – Maskierung“ | Maske aus denselben Kanten wie Datensatz C |
| „Radverkehrsnetz Vorrangnetz“ | heutiger Stand des Geoportals; weicht deshalb stellenweise von Lieferung und Maske ab |
| „REN+ Gesamtnetz“ mit Maskierung | alle Kanten aus allen Netzquellen |
| „Netz“ mit „Maskierung“ | das Kartierungs-Netz |

## Maskierung

`create_mask.py` erzeugt je eine Maskierung für das Gesamtnetz und das Kartierungs-Netz: die Fläche Berlins ohne einen 25-m-Puffer um das Netz, auf 7 m vereinfacht. Sie entspricht der Maskierung des Radvorrangnetzes von 2025 in `tilda-static-data` (`region-infravelo/radverkehrsnetz-vorrangnetz-mask`). Diese entstand 2025 in QGIS und wird seit 2026-10-08 nach demselben Rezept aus Datensatz C erzeugt.

```bash
python ren-network/create_mask.py
```

Ausgabe: `ren-network/output/ren_netz_maske.geojson` und `ren_netz_kartierung_maske.geojson` (WGS84, je ein MultiPolygon). Nach jeder Änderung am Netz neu erzeugen.

## Prüfliste doppelter Kanten

`audit_double_edges.py` sucht Kanten, die denselben Weg doppelt abbilden. Es entfernt nichts; was nach der Prüfung wegfallen soll, wird in der App Netzanpassungen ausgeschlossen (Korrektur „Kante ausschließen“).

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

Zusätzlich: `strassenklasse` (Straßenstufe 0–V aus Hauptstraßennetz bzw. Detailnetz), `netz_quellen` (beteiligte Quellen), `netz_quellen_teilweise` (Quellen, die nur einen Teil der Kante abdecken; `radverkehrsnetz` gilt dann nicht für die ganze Kante), `in_detailnetz` (ja/nein), `bearbeitet_2025` (ja/teilweise/nein), `anteil_2025`, `element_nr_2025`, `hinweis_2025` (siehe [Lieferung 2025](#lieferung-2025)), `element_nr_berechnet` (ja/nein).
