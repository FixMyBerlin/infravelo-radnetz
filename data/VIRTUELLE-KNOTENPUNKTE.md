# Virtuelle Knotenpunkte: Regeln

Gilt für alle Repos im Projekt infraVelo REN+ 2026: `infravelo-radnetz`, `knotenpunkte-app`, `infravelo-ml-knotenpunkte` und alles, was `element_nr` oder Knoten-IDs liest. Stand: 2026-11-12.

Ein virtueller Knotenpunkt ist ein Knoten, den es im Detailnetz nicht gibt. Er teilt eine Kante, wo das Detailnetz keinen Knoten hat, z. B. am Ende eines Radwegs mitten auf einem Straßenabschnitt.

## 1. Eine Quelle

- **Verzeichnis:** [`data/Virtuelle-Knotenpunkte.gpkg`](Virtuelle-Knotenpunkte.gpkg), Layer `Virtuelle-Knotenpunkte`, EPSG:25833, eingecheckt.
- **Werkzeug:** [`data/virtuelle_knotenpunkte.py`](virtuelle_knotenpunkte.py). Nur dieses Skript vergibt Nummern.
- **Alle anderen lesen nur:** Skripte und Apps lesen das Verzeichnis, sie vergeben selbst keine Nummern. Python-Skripte nutzen `read_active()` aus dem Modul.

## 2. Nummer

| Regel | Beispiel |
|---|---|
| Genau 4 Ziffern, mit führenden Nullen, ohne Präfix | `0001`, `0054` |
| Immer Text, nie Zahl | `"0012"`, nicht `12` |
| Hochzählen: neue Nummer = höchste je vergebene + 1 | nach `0053` kommt `0054` |
| Gelöschte Nummern zählen mit und werden nie wieder vergeben | `0054` gelöscht → nächste ist `0055` |
| Die Nummer eines Knotens ändert sich nie, auch nicht beim Verschieben oder bei einem neuen Detailnetz | |

Amtliche Knoten des Detailnetzes haben 8 Ziffern. Trotzdem gilt: **Ob ein Knoten virtuell ist, steht in `ist_virtuell`, nicht in der Form der ID.** Kein Code darf das aus der ID ableiten (früher `startswith('V')`).

Nummern als Text: In GeoPackage und FlatGeobuf als Textspalte, in GeoJSON und CSV als String, in pandas mit `dtype=str`. `pd.to_numeric` oder `int()` auf Knoten-IDs macht aus `0012` die `12` und ist verboten.

## 3. Spalten des Verzeichnisses

| Spalte | Inhalt |
|---|---|
| `Knotenpunkt-ID` | Nummer (mit ASCII-Bindestrich im Spaltennamen; im Knotendatensatz heißt sie `Knotenpunkt‐ID` mit U+2010) |
| `ist_virtuell` | immer `1` |
| `status` | `aktiv` oder `geloescht` |
| `angelegt_am` | Datum `JJJJ-MM-TT`; leer bei den Knoten von vor 2026-11 |
| `geloescht_am`, `grund` | Pflicht bei `geloescht` |
| `alte_id` | Kennung vor der Umnummerierung (`V1112`, `V44530016-44530064` …), sonst leer |
| `quelle` | `QGIS`, `app:<Eintrags-ID>` (Netzanpassungen-App) oder `Bestand (vor 2026-11 mit V-Kennung)` |
| `kommentar` | frei |

`ist_virtuell` (1/0) steht außerdem in jedem Knotendatensatz (`knotenpunkte_gesamt`, `knotenpunkte_bewerten`, Abgabe, Eingabedatei der Netzanpassungen-App). Gesetzt wird es nur aus dem Verzeichnis.

## 4. Anlegen, verschieben, löschen

Virtuelle Knoten werden immer neu angelegt. Ein amtlicher Knoten wird nie zu einem virtuellen umgewandelt, und die Knotenpunkte-App bietet das nicht an.

**Anlegen in QGIS** (funktioniert ohne App):
1. Punkt in `Virtuelle-Knotenpunkte.gpkg` auf die Kante setzen, höchstens 3 m daneben. `Knotenpunkt-ID` leer lassen.
2. `.venv/bin/python data/virtuelle_knotenpunkte.py nummerieren`

**Anlegen in der Netzanpassungen-App:**
1. Den Knoten in der App zeichnen. Bis zur Übernahme trägt er nur einen vorläufigen Namen (`neu-1` …).
2. In der App „Virtuelle Knoten“ exportieren.
3. `.venv/bin/python data/virtuelle_knotenpunkte.py uebernehmen <datei>.geojson`: Das Skript hängt die neuen Knoten an und vergibt die Nummern. Schon übernommene Knoten erkennt es an `quelle = app:<Eintrags-ID>`.
4. `netzanpassungen/export_app_daten.py` laufen lassen und die Datei in die App laden. Die App zeigt dann die Nummer, und Kanten, die in der App an diesem Knoten enden, gehören ab jetzt zu ihm.

**Verschieben:** Den Punkt in QGIS verschieben. Die Nummer bleibt.

**Löschen:** `.venv/bin/python data/virtuelle_knotenpunkte.py loeschen 0012 --grund "…"`. Die Zeile bleibt mit `status = geloescht`, Datum und Grund stehen. So bleibt festgehalten, welche Knoten gelöscht wurden, und die Nummer bleibt gesperrt. Zeilen nie aus der Datei entfernen.

**Prüfen:** `data/virtuelle_knotenpunkte.py pruefen` prüft die Regeln. `processing/validation/validate_virtuelle_knotenpunkte.py` prüft zusätzlich die Lage am REN+ und läuft in `run_validation.sh` mit. Jedes Skript, das das Verzeichnis liest, bricht bei Regelverstößen ab.

## 5. element_nr

- Format `<von>_<bis>.<NN>`, z. B. `50430004_0027.01` oder `0028_51450012.01`.
- In der Prozessierung (`processing/process_radnetz.sh`):
  1. `split_rvn_at_virtual_nodes.py` teilt Zielnetz und Detailnetz an allen aktiven virtuellen Knoten. Toleranz: 3 m.
  2. `assign_element_nr_to_rvn.py` vergibt die `element_nr` neu. An virtuellen Knoten wird nicht über die Kante hinaus zusammengefasst, und die `elem_nr` der Quelle gilt dort nicht.
- **Neues Detailnetz:** Die Prozessierung einfach neu laufen lassen. Die `element_nr` entsteht dann aus den bestehenden Nummern neu; es wird nichts neu nummeriert.
  - Liegt ein Knoten danach mehr als 3 m von jeder Kante, teilt er nichts mehr. `split_rvn_at_virtual_nodes.py` und die Validierung listen ihn auf.
  - Dann den Punkt in QGIS auf die neue Kante schieben (Nummer bleibt) oder ihn löschen (Nummer bleibt gesperrt).
- Gelöschte Knoten teilen nichts. Kanten an ihnen bekommen beim nächsten Lauf wieder die `element_nr` ohne Teilung.

## 6. Umnummerierung 2026-11 und alte Daten

- **Was passiert ist:** Bis 2026-11 hatten die 53 virtuellen Knoten uneinheitliche Kennungen (`V1112`, `V44530016-44530064`, `V44530064-2`, `V47500003-V47500008`). Am 2026-11-12 wurden sie einmalig mit `umnummerieren` auf `0001`–`0053` umgestellt, sortiert nach der alten Kennung.
- **Zuordnung:** [`virtuelle_knotenpunkte_alt_neu.csv`](virtuelle_knotenpunkte_alt_neu.csv). Die Datei wird nie geändert; die gleiche Zuordnung steht in `alte_id`.
- **Alte Datei:** Die Datei vor der Umnummerierung liegt in git (`git show e47bd61:data/Virtuelle-Knotenpunkte.gpkg`).
- **Lieferung 2025:** Datensatz C und der Knotendatensatz 2025 tragen weiter die alten Kennungen (48 Knoten, 210 `element_nr`). Sie werden nicht nachträglich geändert. Zum Vergleich übersetzt `translate_element_nr()` aus dem Modul eine alte `element_nr` (`V6475_V4789.01` → `0039_0022.01`). `knotenpunkt_id_2025` im Knotendatensatz behält die alte Kennung.
- **Bewertungen der Knotenpunkte-App:** Alte Bewertungen unter alter Kennung übersetzt `knotenpunkte/merge_bewertungen.py` beim Zusammenführen. Die Einträge im KV-Projekt `knotenpunkte` werden nicht umbenannt.
- **Netzanpassungen-App:** Verweise auf alte Kennungen (`k:V1112`) in gespeicherten Kanten löst die App über `alte_id` aus der Eingabedatei auf. Auch hier werden KV-Einträge nicht umgeschrieben.
- **Manuelle Listen:** In `data/opposite_edge_overwrite_element_nr.txt` sind die 21 Einträge mit alter Kennung übersetzt. Neue Einträge in solchen Listen immer mit der Nummer schreiben.
