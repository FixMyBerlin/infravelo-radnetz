# Netzanpassungen

Die Skripte hier gehören zur App „Netzanpassungen“ (Repo [knotenpunkte](https://github.com/FixMyBerlin/knotenpunkte), Ordner `netzanpassungen/`) und bilden **Schritt 2, die App-Eingabe und Schritt 3** der Pipeline. Gesamtbild und Regeln: [`docs/netz-ablauf.md`](https://github.com/FixMyBerlin/knotenpunkte/blob/main/docs/netz-ablauf.md) und `NETZKORREKTUR-PLAN.md` im Repo knotenpunkte.

**Grundsatz:** Die Eingabe der App enthält nur Rohdaten und das, was automatisch berechnet wird. Alle Handarbeit (Zuordnungen der Radfernwege, neue Kanten, virtuelle Knoten, Lagekorrekturen, Richtung, Fahrbahn, Ausschluss) liegt ausschließlich in der KV-Datenbank der App und wird dort auf diese Eingabe gelegt. Deshalb darf die Eingabedatei jederzeit neu erzeugt und hochgeladen werden. Schritt 3 schreibt das Ergebnis nur nach `output/`, nie nach `data/`.

```bash
python ren-network/netz_zusammenfuehren.py                  # Schritt 1 (nur bei geänderten Quellen): ren_netz_roh.gpkg
python netzanpassungen/radfernwege_zuordnen.py              # Schritt 2: ren_netz_auto.gpkg, radfernweg_abschnitte.gpkg
python netzanpassungen/app_eingabe_schreiben.py             # App-Eingabe, ganz Berlin
python netzanpassungen/app_eingabe_schreiben.py --bezirk Neukölln
python netzanpassungen/app_ergebnis_anwenden.py <export-alle-eintraege>.json   # Schritt 3: Export der App zurück
python netzanpassungen/app_ergebnis_anwenden.py --ohne-export                  # Schritt 3 ohne Handarbeit
python netzanpassungen/test_radfernwege_zuordnen.py         # Selbsttests
python netzanpassungen/test_app_ergebnis_anwenden.py
```

| Skript (bisher) | Aufgabe |
|---|---|
| `radfernwege_zuordnen.py` (neu) | Schritt 2: Radfernwege automatisch auf Rohnetz und Detailnetz legen, in Abschnitte zerlegen |
| `app_eingabe_schreiben.py` (`export_app_daten.py`) | schreibt `netzanpassungen_<gebiet>.json` für die App |
| `app_ergebnis_anwenden.py` (`import_app_export.py`) | Schritt 3: App-Export auf `ren_netz_auto.gpkg` anwenden, Ergebnisnetze und Kartierung schreiben |

## Schritt 2: Radfernwege zuordnen

`radfernwege_zuordnen.py` liest `ren-network/output/ren_netz_roh.gpkg`, das Detailnetz und `data/netzquellen/touristisches_radnetz.gpkg` (GPS-Linien von 8 Routen). Eine Kante gehört zur Route, wenn mindestens **60 %** ihrer Länge höchstens **20 m** von der Route entfernt liegen **und** die Route dort **unter 45°** parallel läuft (Stützpunkte alle 5 m, Richtung über ±8 m). Der Winkel hält Querstraßen an Kreuzungen draußen. Kanten ab 40 % sind Kandidaten für die App. Hausdorff und das 95. Perzentil sind Kennzahlen je Abschnitt, kein Kriterium. Begründung der Werte: Abschnitt „Zuordnungsregel“ in `docs/netz-ablauf.md` (Repo knotenpunkte). Die Werte stehen oben in `radfernwege_zuordnen.py`.

- REN+-Kanten bekommen `routen_fernradweg` und `routen_quelle = auto`.
- Detailnetzkanten, die noch nicht im REN+ sind (z. B. Markgrafenstraße), kommen als Zeilen ins Netz (`quelle = detailnetz_radfernweg`, `grund_aufnahme = radfernweg`), wenn nicht schon eine zugeordnete REN+-Kante dieselbe Strecke trägt (höchstens die Hälfte der Strecke darf schon von REN+ abgedeckt sein). Autobahnen und Zubringer (`AUBA`/`AUTO`) bleiben draußen.
- Jede Route wird **lückenlos** in Abschnitte zerlegt: `auf_ren` (auf REN+-Kanten), `aufgenommen` (auf aufgenommenen Detailnetzkanten) oder `luecke` (keine eindeutige Kante). Abschnitte enden, wo die Kantenmenge wechselt; Stücke unter 25 m gleichen Zustands, Lücken unter 20 m und Stücke unter 5 m gehen im Nachbarn auf. Die Id ist fest: `<route-slug>@<von_m>-<bis_m>` (ganze Meter entlang der Route), bei gleichen Eingangsdaten in jedem Lauf gleich.

Ausgabe in `netzanpassungen/output/` (nicht versioniert):

- `ren_netz_auto.gpkg` (Layer `ren_netz`): das Rohnetz plus `verkehrsrichtung` (B/R/G per `element_nr` aus dem Detailnetz), `quelle` (`radnetz` | `detailnetz_radfernweg`), `grund_aufnahme`, `routen_fernradweg` (mehrere Routen mit `; `), `routen_quelle` und die aufgenommenen Detailnetzkanten
- `radfernweg_abschnitte.gpkg` (Layer `radfernweg_abschnitte`): `id`, `radfernweg`, `station_von_m`, `station_bis_m`, `laenge_m`, `zustand`, `kanten` und `kandidaten` (Kanten-Schlüssel der App mit `|` getrennt: `ren:<ref>`, `detailnetz:<ref>`), `hausdorff_m` und `p95_m` (Abstand vom Abschnitt zu seinen Kanten, einseitig; bei `luecke` leer)

Der Schlüssel `ref` ist der der App (`line_refs` in `app_eingabe_schreiben.py`, entspricht `lineRefs` in `model.ts`): die `element_nr`, ab der zweiten Linie derselben Nummer `#2`, ...; gezählt wird in der Reihenfolge der Datei (REN+: `ren_netz_auto.gpkg`, Detailnetz: jüngste `.fgb`). Mit `--bezirk` kann sich diese Zählung für Nummern mit mehreren Linien gegenüber ganz Berlin verschieben.

## App-Eingabe

`app_eingabe_schreiben.py` schreibt die Eingabedatei der App. Die Datei enthält nur Rohdaten und das Ergebnis von Schritt 2. Der Kopf `ren_netz_stand` hält `datei`, `datum` und `sha256` von `ren_netz_auto.gpkg`, auf dem die Korrekturen der App beruhen.

| Datei | Inhalt |
|---|---|
| `data/Berlin Straßenabschnitte Detailnetz*.fgb` | Detailnetzkanten, jüngster Stand wie in `netz_zusammenfuehren.py` |
| `netzanpassungen/output/ren_netz_auto.gpkg`, `radfernweg_abschnitte.gpkg` | Ergebnis von Schritt 2 |
| `data/netzquellen/touristisches_radnetz.gpkg` | Radfernwege, aus dem Drive (`data/download_inputs.py`, läuft zu Beginn) |
| `data/Berlin Bezirke.gpkg` | nur mit `--bezirk` |

Ausgabe in `netzanpassungen/output/`:

- `netzanpassungen_<gebiet>.json`: Schema `netzanpassungen-app/v1`, WGS84 mit 7 Nachkommastellen, FeatureCollections:
  - `detailnetz`: `element_nr`, `beginnt_bei_vp`, `endet_bei_vp`, `strassenname`, `verkehrsebene`, `okstra_id`
  - `knoten`: nur Detailnetzknoten (`id`, `ist_virtuell` = 0) aus den Kantenenden (erster Punkt = `beginnt_bei_vp`, letzter = `endet_bei_vp`). Virtuelle Knoten stehen nicht in der Datei, sie leben in der App; die 53 von 2025 liegen in `einmalige_uebernahme/virtuelle_knoten_2025.json`.
  - `ren_netz`: `element_nr`, `von_knoten`, `bis_knoten` (als Text), `radverkehrsnetz`, `strassenname`, `verkehrsrichtung` (B beide Richtungen, R nur in Linienrichtung, G nur dagegen), und die optionalen Felder `routen_fernradweg`, `routen_quelle` (`auto` oder leer), `quelle` (`radnetz` | `detailnetz_radfernweg`). MultiLineStrings sind in Teile zerlegt. Die Datei ist das ganze Netz aus Schritt 2, nicht nur die Kartierung.
  - `radfernwege`: `name`
  - `radfernweg_abschnitte`: die Abschnitte von Schritt 2 mit Listen in `kanten` und `kandidaten`
  - `luecken`: die Abschnitte mit `zustand = luecke` ab 20 m Länge (Arbeitsliste der App), mit `id` (= Abschnitts-Id), `name` und `laenge_m`. Der Abgleich ist nicht mehr „10 m um irgendeine Kante“ (bisher `find_gaps`), sondern die Zuordnungsregel von Schritt 2.
  - `knoten_vorschlaege` (Test): Punkte, an denen ein Radfernweg eine Detailnetzkante kreuzt, mindestens 15 m von jedem Knoten entfernt (Kreuzungen auf derselben Kante unter 10 m werden zusammengelegt). Felder: `element_nr`, `strassenname`, `verkehrsebene`, `routen`, `winkel_grad`, `steil` (Schnittwinkel ab 30°), `luecke_nah` (Anfang oder Ende einer Lücke innerhalb 25 m), `station_m`, `abstand_ende_m`.
- `pruefliste_<gebiet>.csv`: Kantenenden, die mehr als 0,5 m neben ihrem Knoten liegen (Stand 2026-11-11: eins)

Mit `--bezirk` bleiben Kanten, Knoten und Radfernwege bis 200 m über die Bezirksgrenze hinaus enthalten; Zuordnung und Abschnitte werden vorher für ganz Berlin berechnet.

## Schritt 3: App-Ergebnis anwenden

`app_ergebnis_anwenden.py` liest den Export „alle Einträge“ der App (`{gebiet, exported_at, entries}`; Einträge mit `geloescht` werden übersprungen) und `ren_netz_auto.gpkg` und schreibt:

- `ren-network/output/ren_netz.gpkg` (**Kunde**: Originallage, mit Radfernwegen, Richtung, Fahrbahn, Ausschluss, alles markiert) und `ren_netz_korrigiert.gpkg` (**Matching und Mapping**: zusätzlich die Lagekorrekturen mit `lage_korrigiert` und Kennzahlen), jeweils mit `.geojson` und der Kartierung (`ren_netz_kartierung.gpkg`, `ren_netz_kartierung_korrigiert.gpkg`: ohne `bearbeitet_2025 = ja` und ohne ausgeschlossene Kanten). Spalten, Prüfungen (5 cm gegen `original_coordinates`, Wiederholung des Protokolls) und die Verwendung: [`ren-network/README.md`](../ren-network/README.md#ergebnisnetze-schritt-3).
- `ren-network/output/korrekturen_konflikte.csv` und `radfernweg_zuordnungen.csv`
- `netzanpassungen/output/virtuelle_knoten.gpkg`: alle nicht gelöschten virtuellen Knoten des Exports (Layer `Virtuelle-Knotenpunkte`: `Knotenpunkt-ID`, `ist_virtuell`, `traeger_netz`, `traeger_element_nr`, `station_m`, `kommentar`, `eintrag_id`; EPSG:25833). Das ist die Datei, die `processing/` und `knotenpunkte/` über `processing/helpers/virtuelle_knoten.py` lesen; fehlt sie, brechen sie mit dem Hinweis ab, erst Schritt 3 laufen zu lassen. Gezeichnete Kanten stehen in `netzanpassungen/output/touristische_kanten.gpkg` (Layer `touristische_kanten`: `entry_id`, `element_nr`, `von_knoten`, `bis_knoten` als Text, `quelle`, `strassenname`, `routen_fernradweg`, `kommentar`). Die `element_nr` zählt wie in der App (`von_bis.NN`, in der Reihenfolge des Zeichnens, nach Detailnetz und REN+); das Teilen an virtuellen Knoten übernimmt `processing/scripts/split_rvn_at_virtual_nodes.py`. Beide Dateien entstehen bei jedem Lauf neu aus dem Export (mit `--ohne-export` bleiben sie unangetastet).

**Zuordnungen** (`section_assignment`, ein Eintrag je Abschnitt aus `radfernweg_abschnitte.gpkg`):

- `zugeordnet`: die gewählten Kanten (`ren:<ref>` oder `detailnetz:<ref>`) bekommen die Route in `routen_fernradweg`; `routen_quelle` wird `manuell`, bei einer Kante mit automatischer Route `auto; manuell`. Eine Detailnetzkante, die noch nicht im Netz liegt, wird als Zeile aufgenommen (`quelle = detailnetz_manuell`, `grund_aufnahme = radfernweg_manuell`); liegt sie als REN+-Kante schon im Netz, bekommt nur diese die Route.
- **Umlegung:** Ersetzt der Eintrag die automatische Zuordnung des Abschnitts (andere Kanten als die in `kanten` von Schritt 2), verlieren die bisherigen Kanten diese Route, außer eine andere nicht ersetzte Zuordnung derselben Route trägt sie noch. Eine in Schritt 2 aufgenommene Detailnetzkante, die danach keine Route mehr hat, entfällt.
- `keine_aktion`: ändert nichts am Netz, steht nur in `radfernweg_zuordnungen.csv`.
- Unbekannter Abschnitt, falscher Radfernweg zum Abschnitt, unbekannte Kante oder mehrere Einträge zum selben Abschnitt: Eintrag gilt nicht, Zeile in `korrekturen_konflikte.csv` (bei mehreren gilt der jüngste).

Achtung Kartierung: Der TILDA-Datensatz `infravelo-ren-netz-kartierung` (Symlink in `tilda-static-data`, außerhalb dieses Repos) muss auf `ren_netz_kartierung_korrigiert.geojson` zeigen.

**Gezeichnete Kanten und virtuelle Knoten in den Ergebnisnetzen.** `ren_netz.gpkg` und `ren_netz_korrigiert.gpkg` enthalten die in der App gezeichneten Kanten (`new_edge`, nicht gelöscht): `quelle = neu_gezeichnet`, `routen_fernradweg` aus dem Eintrag mit `routen_quelle = manuell`, `grund_aufnahme = radfernweg_manuell` bei Herkunft `radfernweg`, `eintrag_ids`, `element_nr` wie in der App (`<von>_<bis>.<nn>`, `nn` zählt je Knotenpaar nach den vorhandenen Kanten, in der Reihenfolge des Zeichnens). Die virtuellen Knoten des Exports teilen ihre Trägerkante (REN+-Kante oder gezeichnete Kante) wie `splitEdges` in der App: Jede Teilkante hat eine neue `element_nr` (zuerst die Teile gezeichneter Kanten) und `ursprung_element_nr`, die Ursprungszeile entfällt. Die Station ergibt sich aus der Lage des Knotens auf der Kante (im Arbeitsnetz auf der korrigierten Linie, im Kundennetz beim gleichen Anteil der Länge); ein Knoten mehr als 1 m neben seiner Kante oder an einer Kante mit mehreren Linien oder ohne Knoten teilt nicht (Hinweis in `korrekturen_konflikte.csv`). `von_knoten`/`bis_knoten` sind in diesen Netzen Text, weil virtuelle IDs mit `V` beginnen. `processing/scripts/split_rvn_at_virtual_nodes.py` teilt weiterhin Detailnetz und Radvorrangsnetz geometrisch (ohne Nummern) und lässt bereits geteilte REN+-Kanten wegen der 1-m-Toleranz an den Enden unberührt.

## Altlisten

[`einmalige_uebernahme/`](./einmalige_uebernahme/README.md) enthält die Dateien für die einmalige Übernahme in die App. `altlisten_korrekturen.json` enthält die Altlisten als `edge_correction`-Einträge (`von_nutzer: "Altliste"`) zum Einspielen in der App („Korrekturen einspielen“): `verkehrsrichtung` aus `rvn_korrekturen.csv` und `opposite_edge_overwrite_element_nr.txt` (Modus `remove`, nur Kanten mit Detailnetz-`verkehrsrichtung` B, neu R) sowie die Ausschlüsse aus `ausschluss_element_nr.csv`. Die drei Listen und der Code, der sie las, sind entfernt (darunter `processing/helpers/override_edges.py`, `processing/validation/analyse_einrichtungsfahrbahnen.py` und `processing/qgis/erzeuge_einrichtungsfahrbahnen_projekt.py`); erzeugt hat die Datei ein einmaliges Skript, das nicht im Repo liegt (Stand 2026-11-10).

## QGIS-Stil

`netz-aenderungen.qml` stylt den GeoJSON-Export `netz-aenderungen` der App nach `darstellung`: `alt` grau gestrichelt, `neu` blau, `differenz` rot halbtransparent, `vektor` roter Pfeil von alt nach neu mit `abstand_m` als Beschriftung, `attribut` orange, `gruppe` grün dünn gestrichelt. Der Export enthält Linien und Flächen; QGIS legt dafür zwei Layer an, auf beide den Stil laden (Layer-Eigenschaften, Symbolisierung, Stil, Stil laden).
