# Virtuelle Knotenpunkte: Regeln

Gilt für alle Repos im Projekt infraVelo REN+ 2026: `infravelo-radnetz`, `infravelo-apps` (App Netzanpassungen), `knotenpunkte-app`, `infravelo-ml-knotenpunkte` und alles, was `element_nr` oder Knoten-IDs liest. Stand: 2026-11-19.

Ein virtueller Knotenpunkt ist ein Knoten, den es im Detailnetz nicht gibt. Er teilt eine Kante, wo das Detailnetz keinen Knoten hat, z. B. am Ende eines Radwegs mitten auf einem Straßenabschnitt.

## 1. Wo virtuelle Knoten entstehen und stehen

- **Die App Netzanpassungen ist der einzige Ort, an dem virtuelle Knoten angelegt, verschoben und gelöscht werden, und sie vergibt ihre Nummern** (seit 2026-11-19). Kein Bearbeiten in QGIS, kein `virtuelle_knotenpunkte.py nummerieren` oder `uebernehmen` mehr.
- **Die 53 Knoten von 2025** (`0001`–`0053`) sind Einträge der App (KV-Datenbank, `virtual_node` mit `herkunft: rvn_2025`, `nummer`, `id_rvn_2025`, feste Eintrags-Ids `rvn2025-0001` …). Die App hat sie einmalig selbst übernommen, als ein angemeldeter Nutzer das Gebiet `berlin` geöffnet hat (`netzanpassungen/src/network/take-over-2025.ts` in infravelo-apps). Die Lieferung liegt seitdem als Archiv in [`netzanpassungen/one_time_import/2025/Virtuelle-Knotenpunkte.gpkg`](../netzanpassungen/one_time_import/2025/Virtuelle-Knotenpunkte.gpkg) (Layer `Virtuelle-Knotenpunkte`, EPSG:25833) und wird von der Pipeline nicht mehr gelesen (nur Tests und `old_to_new()` für alte Kennungen). Ab der Übernahme zählen nur noch die Daten der App.
- **Die Pipeline liest die 53 aus der KV-Datenbank:** `read_registry()` in [`virtuelle_knotenpunkte.py`](virtuelle_knotenpunkte.py) braucht `VITE_KV_*` in `.env` (wie Schritt 3) und bricht mit einem Hinweis ab, wenn nicht alle 53 da sind (dann das Gebiet `berlin` einmal angemeldet in der App öffnen). Schritt 1 teilt das REN+ an den aktiven; die Eingabedatei der App enthält sie nicht als `knoten` (die App hat sie als Einträge).
- **Alle Knoten zusammen** schreibt Schritt 3 (`netzanpassungen/apply_app_result.py`) bei jedem Lauf nach `netzanpassungen/output/virtuelle_knoten.gpkg`: die 53 und jeden nummerierten Knoten der App, aktiv und gelöscht (die Zeilen der 53 aus ihren Einträgen).
- **Alle anderen lesen nur:** Python-Skripte nutzen `read_active()` aus [`data/virtuelle_knotenpunkte.py`](virtuelle_knotenpunkte.py); es liest `virtuelle_knoten.gpkg` und bricht mit dem Hinweis ab, erst Schritt 3 laufen zu lassen, wenn die Datei fehlt.

## 2. Nummer

| Regel | Beispiel |
|---|---|
| Genau 4 Ziffern, mit führenden Nullen, ohne Präfix | `0001`, `0054` |
| Immer Text, nie Zahl | `"0012"`, nicht `12` |
| Hochzählen: neue Nummer = höchste je vergebene + 1 | nach `0053` kommt `0054` |
| Gelöschte Nummern zählen mit und werden nie wieder vergeben | `0054` gelöscht → nächste ist `0055` |
| Die Nummer eines Knotens ändert sich nie, auch nicht beim Verschieben oder bei einem neuen Detailnetz | |

Die App zählt mit dem Eintrag `zaehler:virtuelle-knoten` in ihrer KV-Datenbank (`letzte_nummer`, Start 53, gilt über alle Gebiete). Ein Knoten der App trägt seine Nummer in `nummer` (und gleich in `name`).

Amtliche Knoten des Detailnetzes haben 8 Ziffern. Trotzdem gilt: **Ob ein Knoten virtuell ist, steht in `ist_virtuell`, nicht in der Form der ID.** Kein Code darf das aus der ID ableiten (früher `startswith('V')`).

Nummern als Text: In GeoPackage und FlatGeobuf als Textspalte, in GeoJSON und CSV als String, in pandas mit `dtype=str`. `pd.to_numeric` oder `int()` auf Knoten-IDs macht aus `0012` die `12` und ist verboten.

## 3. Spalten

`netzanpassungen/output/virtuelle_knoten.gpkg` (dieselben Spalten wie das Archiv der 53 in `netzanpassungen/one_time_import/2025/`):

| Spalte | Inhalt |
|---|---|
| `Knotenpunkt-ID` | Nummer (mit ASCII-Bindestrich im Spaltennamen; im Knotendatensatz heißt sie `Knotenpunkt‐ID` mit U+2010) |
| `ist_virtuell` | immer `1` |
| `status` | `aktiv` oder `geloescht` |
| `angelegt_am` | Datum `JJJJ-MM-TT`; `2025` bei den 53 von 2025 |
| `geloescht_am`, `grund` | bei `geloescht` (aus der App; fehlt der Grund, „in der App gelöscht“) |
| `id_rvn_2025` | Kennung in der Lieferung 2025 (`V1112`, `V44530016-44530064` …), nur bei den 53; bis 2026-11-19 hieß die Spalte `alte_id` |
| `quelle` | `RVN 2025` bei den 53, `Netzanpassungen-App` sonst |
| `kommentar` | frei |

Nur in `virtuelle_knoten.gpkg`: `herkunft` (`2025` bei den 53; aus der App `gezeichnet`, `luecke`, `teilung` oder `vorschlag`), `app_eintrag` (KV-Id des Eintrags), `vorschlag_id` (bei `herkunft = vorschlag`), `traeger_netz`, `traeger_element_nr`, `station_m` (Kante, auf der der Knoten liegt).

`ist_virtuell` (1/0) steht außerdem in jedem Knotendatensatz (`knotenpunkte_gesamt`, `knotenpunkte_bewerten`, Abgabe, Eingabedatei der Netzanpassungen-App).

## 4. Anlegen, verschieben, löschen (in der App)

Virtuelle Knoten werden immer neu angelegt. Ein amtlicher Knoten wird nie zu einem virtuellen umgewandelt.

Jeder neue Knoten bekommt sofort seine Nummer. Es gibt vier Fälle:

1. **Neue Kante zeichnen:** Ein Ende auf einer Kante oder ein freies Ende (Sackgasse) setzt einen Knoten (`herkunft = gezeichnet`).
2. **Lücke im Netz schließen:** Das offene Ende einer Kante auf eine Kante ziehen (`luecke`).
3. **Kante auf Wunsch teilen**, ohne zu zeichnen: Kante wählen, „Knoten auf Kante setzen“ (`teilung`).
4. **Knotenvorschlag übernehmen** (`vorschlag`): Schritt 1 (`ren-network/merge_networks.py`) findet Stellen, an denen REN+-Kanten ohne Knoten aufeinandertreffen: ein Kantenende auf dem Inneren einer anderen Kante (`on_edge`), Kantenenden, die sich ohne Knoten treffen (`junction`), offene Enden (`dead_end`). Er teilt das Netz dort schon und nennt die Stelle nach ihrer Lage `P<x>-<y>` (Koordinaten in EPSG:25833 auf ganze Meter, z. B. `P391234-5818765`; gleich, solange sich das Netz dort nicht ändert). Die App zeigt sie in „Knotenvorschläge Netz“; „Übernehmen“ gibt eine Nummer, der Eintrag hält die Vorschlags-Id in `vorschlag_id`. Schritt 3 ersetzt die Vorschlags-Id durch die Nummer. Offene Vorschläge bleiben mit ihrer `P…`-Id als Kantenende stehen und stehen in `korrekturen_konflikte.csv` als „Knotenvorschlag noch nicht übernommen“; Knotenpunkte sind sie erst nach der Übernahme.

**Verschieben:** in der App. Die Nummer bleibt.

**Löschen:** in der App. Der Eintrag bleibt mit `geloescht = true` (`geloescht_am`, `grund`), die Nummer bleibt gesperrt; in `virtuelle_knoten.gpkg` steht er mit `status = geloescht`.

Die 53 von 2025 sind nach der Übernahme gewöhnliche Einträge der App: Verschieben und Löschen wie bei jedem Knoten. Ein gelöschter behält seine Nummer (`status = geloescht`).

**Ältere Einträge ohne Nummer** (vorläufige Namen `neu-<n>`, alte `V…`-Namen) nummeriert die App einmalig, älteste zuerst, wenn ein Admin das Gebiet öffnet. Bis dahin zählen sie in Schritt 3 nicht (Hinweis in `korrekturen_konflikte.csv`).

**Prüfen:** `.venv/bin/python data/virtuelle_knotenpunkte.py pruefen` prüft die Regeln für das Archiv der 53 (unverändert) und für `virtuelle_knoten.gpkg`. Die Prüfungen `VK-…` in `processing/validation/checks/virtuelle_knotenpunkte.py` prüfen zusätzlich die Lage am REN+ und laufen in `run_validation.sh` mit. Jedes Skript, das die Knoten liest, bricht bei Regelverstößen ab.

## 5. element_nr

- Format `<von>_<bis>.<NN>`, z. B. `50430004_0027.01` oder `0028_51450012.01`. An einem offenen Knotenvorschlag steht die Vorschlags-Id: `P391234-5818765_51450012.01`.
- Schritt 1 teilt das REN+ an den aktiven der 53 (aus der App) und an den Knotenvorschlägen und nummeriert; Schritt 3 teilt an den Knoten der App und ersetzt übernommene Vorschlags-Ids durch die Nummer (die `element_nr` der App-Eingabe bleibt dann in `element_nr_eingabe`).
- In der Prozessierung (`processing/process_radnetz.sh`):
  1. `split_rvn_at_virtual_nodes.py` teilt Zielnetz und Detailnetz an allen aktiven virtuellen Knoten aus `virtuelle_knoten.gpkg`. Toleranz: 3 m.
  2. `assign_element_nr_to_rvn.py` vergibt die `element_nr` neu. An virtuellen Knoten wird nicht über die Kante hinaus zusammengefasst, und die `elem_nr` der Quelle gilt dort nicht.
- **Neues Detailnetz:** Die Pipeline einfach neu laufen lassen. Liegt ein Knoten danach mehr als 3 m von jeder Kante, teilt er nichts mehr; `split_rvn_at_virtual_nodes.py` und die Validierung listen ihn auf. Dann den Knoten in der App auf die neue Kante schieben (Nummer bleibt) oder ihn löschen (Nummer bleibt gesperrt).
- Gelöschte Knoten teilen nichts. Kanten an ihnen bekommen beim nächsten Lauf wieder die `element_nr` ohne Teilung.

## 6. Umnummerierung 2026-11 und alte Daten

- **Was passiert ist:** Bis 2026-11 hatten die 53 virtuellen Knoten uneinheitliche Kennungen (`V1112`, `V44530016-44530064`, `V44530064-2`, `V47500003-V47500008`). Am 2026-11-12 wurden sie einmalig auf `0001`–`0053` umgestellt, sortiert nach der alten Kennung.
- **Erledigt und entfernt (2026-11-19):** die Befehle `nummerieren`, `uebernehmen`, `loeschen` und `umnummerieren` von `virtuelle_knotenpunkte.py` (Nummern gibt nur noch die App) sowie die Spalte `alte_id` (heißt jetzt `id_rvn_2025`). Die Fassung mit den Befehlen liegt in git (`git log -- data/virtuelle_knotenpunkte.py`).
- **Zuordnung:** [`virtuelle_knotenpunkte_alt_neu.csv`](virtuelle_knotenpunkte_alt_neu.csv) (Spalten `id_rvn_2025`, `neue_id`). Die Zuordnung ändert sich nie; dieselbe steht in `id_rvn_2025`.
- **Alte Datei:** Die Datei vor der Umnummerierung liegt in git (`git show e47bd61:data/Virtuelle-Knotenpunkte.gpkg`).
- **Lieferung 2025:** Datensatz C und der Knotendatensatz 2025 tragen weiter die alten Kennungen (48 Knoten, 210 `element_nr`). Sie werden nicht nachträglich geändert. Zum Vergleich übersetzt `translate_element_nr()` aus dem Modul eine alte `element_nr` (`V6475_V4789.01` → `0039_0022.01`). `knotenpunkt_id_2025` im Knotendatensatz behält die alte Kennung.
- **Bewertungen der Knotenpunkte-App:** Alte Bewertungen unter alter Kennung übersetzt `knotenpunkte/merge_bewertungen.py` beim Zusammenführen. Die Einträge im KV-Projekt `knotenpunkte` werden nicht umbenannt.
- **Netzanpassungen-App:** Verweise auf alte Kennungen (`k:V1112`) in gespeicherten Kanten löst die App (und Schritt 3) über `id_rvn_2025` der Einträge auf. KV-Einträge werden nicht umgeschrieben.
- **Manuelle Listen:** In `netzanpassungen/one_time_import/2025/opposite_edge_overwrite_element_nr.txt` (bis 2026-11 `data/`, jetzt Archiv) sind die 21 Einträge mit alter Kennung übersetzt.
