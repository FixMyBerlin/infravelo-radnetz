# Knotenpunkte

`build_knotenpunkte.py` erstellt den Knotenpunkt-Datensatz für alle Netzknoten des [REN+-Netzes](../ren-network/README.md). Knoten aus der Lieferung 2025 (Radvorrangnetz) bleiben enthalten, samt ihren Bewertungen, und sind mit `bearbeitet_2025 = ja` markiert. Alle anderen Knoten gehen zur Bewertung an die [Knotenpunkt-App](https://github.com/FixMyBerlin/knotenpunkte) und an [infravelo-ml-knotenpunkte](https://github.com/FixMyBerlin/infravelo-ml-knotenpunkte).

```bash
python ren-network/unify_networks.py      # REN+-Netz
python knotenpunkte/download_lsa.py       # Lichtsignalanlagen (einmalig, --neu lädt erneut)
python knotenpunkte/build_knotenpunkte.py
```

## Kette im Überblick

```bash
# 1. Knoten bauen (infravelo-radnetz)
python ren-network/unify_networks.py                  # nur bei geändertem REN+
python knotenpunkte/build_knotenpunkte.py

# 2. ML-Vorschläge auf Luftbild 2026 (infravelo-ml-knotenpunkte)
cd ../infravelo-ml-knotenpunkte
cp -f ../infravelo-radnetz/knotenpunkte/output/knotenpunkte_bewerten.geojson _input/bewerten.geojson
export DOP_TOKEN=...                                  # für fehlende 2026-Kacheln
uv run python 04_vorhersage.py
uv run python 06_export_knotenpunkte.py               # -> _output/knotenpunkte_vorschlaege.json

# 3. Knotenpunkt-App: knotenpunkte_bewerten.geojson importieren, knotenpunkte_vorschlaege.json hochladen
# 4. Bewertungen exportieren und übernehmen (infravelo-radnetz)
python knotenpunkte/merge_bewertungen.py ratings-<bereich>-<datum>.geojson
```

## Eingangsdaten

| Datei | Inhalt |
|---|---|
| `ren-network/output/ren_netz_gesamt.gpkg` | REN+-Kanten mit `von_knoten`, `bis_knoten`, `radverkehrsnetz`, `hauptverkehrsstrasse` |
| `data/Berlin Verbindungspunkte Detailnetz.fgb`, `data/Berlin Straßenabschnitte Detailnetz*.fgb` | Lage und `okstra_id` der Knoten |
| `data/Virtuelle-Knotenpunkte.gpkg` | Manuell gepflegte virtuelle Knoten (`Knotenpunkt-ID`, Punkt) |
| `data/Berlin Bezirke.gpkg` | Bezirksnummer |
| `data/netzquellen/knotenpunkte_2025.geojson.gz` | Lieferung 2025, gzip von `knotenpunkte_mit_id_und_bezirken.geojson` aus `tilda-static-data` (`region-infravelo/infravelo-datensatz-knoten-fortlaufend`) |
| `data/netzquellen/lsa.gpkg`, `osm_ampeln.gpkg` | Ampeln aus Open Data (WFS `lsa`) und OSM, von `download_lsa.py` |

## Ablauf

1. **Knoten**: alle `von_knoten`/`bis_knoten` des REN+. Die Lage kommt vom Verbindungspunkt, sonst vom Kantenende im Detailnetz und zuletzt vom Kantenende im REN+.
2. **Virtuelle Knoten** aus der manuellen Datei. Anliegende Kanten werden im Umkreis von 3 m gesucht.
3. **Netzattribute** der anliegenden Kanten: `ist_radvorrangnetz` nach höchstem Rang (Vorrang > Ergänzung > keins). `KP_HVS` ist 1, wenn eine Kante Hauptverkehrsstraße ist.
4. **Bezirk** aus den Bezirksgrenzen. Liegt ein Punkt außerhalb, gilt der nächste Bezirk.
5. **LSA**: Ampel aus Open Data und OSM im Umkreis von 25 m. Melden beide eine Ampel, ist `LSA_KP` 1, meldet keine, ist es 0. Melden die Quellen Widersprüchliches, bleibt es leer, und der Grund steht in `LSA_Konflikt`. Der Radius ist gegen die Lieferung 2025 kalibriert.
6. **Lieferung 2025**: Abgleich über die ID, sonst über die Lage (5 m). Für gelieferte Knoten werden die Bewertungen übernommen. `KP_HVS` und `LSA_KP` von 2025 ersetzen dabei die abgeleiteten Werte.
7. **Betrachtung** = Hauptverkehrsstraße oder LSA. Das Feld ist nur ein Hinweis, kein Filter.

## Ausgabe

In `knotenpunkte/output/`:

| Datei | Inhalt |
|---|---|
| `knotenpunkte_gesamt.gpkg` / `.geojson` | Alle Knoten (GPKG in EPSG:25833, GeoJSON in WGS84) |
| `knotenpunkte_bewerten.geojson` | Nur `bearbeitet_2025 = nein`, Eingabe für App und ML |
| `knotenpunkte_vorschlaege.json` | ML-Vorschläge je Knoten und Attribut aus `infravelo-ml-knotenpunkte`, hier abgelegt für den Upload in die App |
| `pruefliste.csv` | Auffälligkeiten mit `lon`/`lat`: Lage-Rückfälle, 2025-Knoten ohne Treffer, abweichende Werte 2025, Knoten, die das Netz nicht erreicht, Kanten ohne Knoten |
| `knotenpunkte_abgabe.gpkg` / `.geojson` | Abgabestand nach `merge_bewertungen.py` |

## Attribute

| Spalte | Inhalt | Herkunft |
|---|---|---|
| `lfd_nr` | Laufende Nummer | |
| `Knotenpunkt‐ID` | Detailnetz-Knotennummer, bei virtuellen Knoten `V…` (Bindestrich U+2010 wie 2025) | Detailnetz / manuell |
| `okstra_id` | Referenz im Detailnetz | Verbindungspunkt |
| `Bezirksnummer` | `01`–`12` | abgeleitet |
| `ist_radvorrangnetz` | Radvorrangnetz, Radergänzungsnetz oder Kein Radverkehrsnetz vorhanden | REN+ |
| `KP_HVS` | 0/1, Knotenpunkt an Hauptverkehrsstraße | 2025 / App, sonst REN+ |
| `LSA_KP`, `LSA_Konflikt` | 0/1, Lichtsignalanlage; Konflikt `nur_OSM` oder `nur_OpenData` | 2025 / App, sonst Open Data und OSM |
| `Betrachtung` | 0/1: Hauptverkehrsstraße oder LSA (Hinweis) | abgeleitet |
| `Mar_RVF_KP`, `Furt_rot`, `Fl_Linksab`, `vorgez_Fl`, `RFS_Mitte` | `keine`, `teilweise` oder `gänzlich` | 2025 / App (mit ML-Vorschlägen) |
| `KP_Nichtbetrachten`, `Mapillary-ID`, `Kommentar` | Bewertung | 2025 / App |
| `ist_virtuell` | 1 für virtuelle Knoten | manuell / App |
| `bearbeitet_2025`, `knotenpunkt_id_2025` | In der Lieferung 2025 enthalten, ID dort | Abgleich |
| `netz_quellen`, `anzahl_kanten` | Netzquellen und Zahl der anliegenden REN+-Kanten | REN+ |

## Virtuelle und fehlende Knoten

Kanten ohne `element_nr` haben noch keine Knoten (siehe Prüfliste). Deckt eine Netzquelle nur einen Teil eines Detailnetz-Elements ab, liegt der Knoten laut `element_nr` abseits des Netzes. Die Prüfliste meldet das mit „Netz erreicht den Knoten nicht“. Die Verzweigung liegt dann mitten auf dem Element. Neue virtuelle Knoten und Knoten an diesen Kanten werden in `data/Virtuelle-Knotenpunkte.gpkg` ergänzt, mit eindeutiger `Knotenpunkt-ID` (`V…`). Danach `build_knotenpunkte.py` erneut ausführen.

## Bewertung und Abgabe

Knotendatei, ML-Ergebnis, Knotenpunkt-App und Abgabe nutzen dieselben Attribute und Werte (Ja/Nein als 0/1).

1. **ML:** `knotenpunkte_bewerten.geojson` nach `infravelo-ml-knotenpunkte/_input/bewerten.geojson` kopieren. Dann `04_vorhersage.py` und `06_export_knotenpunkte.py` ausführen, das ergibt `knotenpunkte_vorschlaege.json`.
2. **App, in jedem Browser, der bewertet:** Einen Bereich anlegen, z. B. `infravelo-2026`, und `knotenpunkte_bewerten.geojson` importieren. Unter demselben Bereich die Vorschläge hochladen. Knoten und Vorschläge liegen nur lokal im Browser, die Bewertungen werden geteilt.
3. **Abgabe:** Die Bewertungen aus der App als GeoJSON exportieren und übernehmen:

   ```bash
   python knotenpunkte/merge_bewertungen.py ratings-<bereich>-<datum>.geojson
   ```

   Übernommen werden nur vollständig bewertete Knoten. Werte von 2025 bleiben unverändert.
