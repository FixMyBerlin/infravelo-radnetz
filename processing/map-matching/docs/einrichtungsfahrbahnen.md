# Einrichtungsfahrbahnen: Gegenrichtung nicht ausgeben (Plan)

Stand: 16.10.2026. Status: Plan. Umgesetzt sind die RVN-Korrekturliste, das Analyseskript und das QGIS-Prüfprojekt. Die Regel im Map-Matching (Stufe 1) fehlt noch.

## 1. Problem

Das Detailnetz ist an geteilten Fahrbahnen, Einbahn-Ringen um Plätze und ähnlichen Stellen uneinheitlich. Manchmal hat jede Fahrtrichtung eine eigene Kante, manchmal gibt es nur eine gemeinsame Kante. Hat jede Richtung eine eigene Kante, darf diese Kante nur in Fahrtrichtung ausgegeben werden. Die Gegenrichtung liegt dann auf einer anderen Kante.

Das Map-Matching gibt solche Kanten derzeit in beiden Richtungen aus. In die Gegenrichtung (`ri=1`) fallen dabei Wege, die dort fachlich nicht hingehören.

**Beispiel:** `42530048_42530044.02`, Wittenbergplatz. Der Platz ist ein Einbahn-Ring um den U-Bahnhof, die Gegenrichtung läuft über `42530044_42530052` und `42530052_42530048`. In `network_enriched_hmm.fgb` belegt `ri=1` Folgendes:

- die Gehwege auf dem Platz (`way/378949105`, `way/367250367`) mit „Sonstige Wege“
- die Bayreuther Straße mit „Mischverkehr“
- Lücken mit „Keine Radinfrastruktur“

Die Referenz hat nur `ri=0`.

Im Altverfahren hat die manuelle Liste `data/opposite_edge_overwrite_element_nr.txt` diese Stellen gesteuert. Manuelle Listen sind im neuen Verfahren ausgeschlossen. Gesucht ist deshalb eine allgemeine Regel, die diese Stellen erkennt.

## 2. Befunde

### 2.1 `verkehrsrichtung` im Detailnetz erklärt die Liste weitgehend

Das Detailnetz führt `verkehrsrichtung` (`B` = beide Richtungen, `R` = nur in Digitalisierungsrichtung, `G` = nur gegen Digitalisierungsrichtung). `scripts/enrich_rvn_with_detailnetz.py` dreht die Geometrie aller G-Kanten um (geprüft: 38 von 38 gedreht, alle 183 R-Kanten unverändert). **Im RVN (`output/rvn/vorrangnetz_details_combined_rvn.fgb`) ist die Fahrtrichtung damit bei R und G immer `ri=0`.** Das Netz lädt das Feld bereits (`Edge::verkehrsrichtung` in `src/network/mod.rs`).

> `PROBLEME_REGELN.md` (Abschnitt 1.1) wertete „bei G-Kanten behält die Referenz immer `ri=0`“ als Zeichen, dass das Attribut unzuverlässig sei. Wegen des Drehens ist es umgekehrt: Das Verhalten ist konsistent.

Einträge der manuellen Liste nach Modus und `verkehrsrichtung`:

| Modus der Liste | R | G | B | nicht im Detailnetz |
|---|---|---|---|---|
| remove (`ri=1` entfernen) | 145 | 20 | 17 | 1 |
| Gegenrichtung (`ri=1` = „Keine Radinfrastruktur“) | 9 | 0 | 4 | 2 |
| Hinrichtung | 0 | 0 | 1 | 0 |
| Beide | 0 | 0 | 6 | 27 |

Von 183 Remove-Einträgen haben 165 (90 %) R oder G.

### 2.2 Abweichungen

- **R/G ohne Listeneintrag (66 Kanten im RVN):** Die Referenz gibt hier beide Richtungen aus. Zwei Fälle sind zu unterscheiden:
  - Die Gegenrichtung ist echt. Ein Beispiel ist eine Einbahnstraße mit `oneway:bicycle=no`.
  - `ri=1` wurde von der Gegenfahrbahn oder von Nachbarwegen gematcht. Kandidaten dafür sind Stolzenfelsstraße, Rummelsburger Straße, Angerburger Allee und Zufahrt Flughafen Tegel.

  Die TILDA-Wege auf `ri=0` dieser Kanten haben überwiegend `tilda_oneway = yes` (85), aber auch `no` (39).
- **B mit Listeneintrag „remove“ (17 Kanten):** Das sind fast nur Platz-Ringe und Parkwege, und zwar Herrfurthplatz, Müggelbergplatz, Birkenallee, Joachimstraße, Paul-Lincke-Ufer, Urbanpark und Wuhlgartenweg. Hier ist das Detailnetz uneinheitlich, `verkehrsrichtung` hilft nicht.

### 2.3 Bestehende Regeln

- **`main`** (`src/assemble/mod.rs`, `Assembler::edge`): `ri=1` entfällt nur, wenn die Gegenrichtung ganz leer ist und die belegte Richtung nur Einrichtungs-Mischverkehr enthält. Am Wittenbergplatz greift das nicht.
- **Regel-Patch** (`docs/zwischenstand/agent_rules.patch`, nicht übernommen): `[assemble.oneway_rule]` arbeitet mit Längenanteilen aus TILDA-`oneway`. Er greift bei 173 Kanten; bei 141 davon hat auch die Referenz nur eine Richtung. `verkehrsrichtung` nutzt er nicht.

### 2.4 Musteranalyse auf den alten Daten (16.10.2026)

**Grundlage:**

- **Kanten:** alle 5.289 Kanten in `output/rvn/vorrangnetz_details_combined_rvn.fgb`
- **Bezugsdaten:** die manuelle Liste, die Referenz `output/reference-legacy/snapping_network_enriched.fgb` und `data/TILDA Straßen Berlin.fgb`
- **Merkmale je Kante:**
  - Detailnetz: `verkehrsrichtung`, `strassenklasse`
  - Topologie: eine parallele Kante gleichen Namens in 3–60 m Abstand („Zwilling“) und ein alternativer Pfad gleichen Namens zwischen den Endknoten („Ring“)
  - TILDA-Straßen entlang der Kante (Puffer 12 m, gleiche Ausrichtung), als Längenanteil: `oneway` und `oneway_bicycle=no`

Analyseskript: `processing/validation/analyse_einrichtungsfahrbahnen.py`, Ausgabe `output/analysis/einrichtungsfahrbahnen.{fgb,csv}`. 165 Remove-Einträge der Liste liegen im RVN. Die Zahlen unten stammen vom Stand vor den RVN-Korrekturen. Seit den Korrekturen sind alle 165 Remove-Einträge R/G.

**Ergebnis 1: Das Detailnetz zeigt seine Aufspaltung selbst an.** Ist eine Fahrbahn im Detailnetz in Richtungskanten aufgeteilt, haben diese Kanten `verkehrsrichtung` R oder G. Ist sie nicht aufgeteilt, steht dort B, auch wenn OSM zwei Richtungsfahrbahnen hat (`yes_dual_carriageway`).

| `verkehrsrichtung` | Kanten im RVN | davon Liste „remove“ |
|---|---|---|
| R | 188 | 127 |
| G | 40 | 20 |
| B | 4.720 | 17 |
| ohne (Kanten nicht aus dem Detailnetz) | 341 | 1 |

**Ergebnis 2: R/G-Kanten lassen sich mit TILDA vollständig auftrennen.** Die R/G-Kanten wurden in drei Gruppen eingeteilt:

- **Gruppe A:** `ri=1` fehlt in der Referenz oder ist „Keine Radinfrastruktur“, oder die Kante steht in der Liste.
- **Gruppe B:** Die Referenz hat in `ri=1` einen Zweirichtungsweg.
- **Gruppe C:** Die Referenz hat in `ri=1` einen Einrichtungsweg.

| R/G-Kanten (228) | A | B | C |
|---|---|---|---|
| `oneway_bicycle=no` auf der Fahrbahn (> 30 %) | 0 | 15 | 7 |
| Fahrbahn Einbahn (> 80 %), keine Freigabe | 163 | 10 | 21 |
| kaum TILDA-Einbahn (Fahrbahn fehlt oder ist Zweirichtung) | 7 | 4 | 1 |

Daraus folgt die Regel: **R/G und keine Freigabe für die Gegenrichtung und kein Zweirichtungsweg in `ri=1` → `ri=1` entfällt.** Auf den alten Daten liefert sie:

- **richtig erkannt:** 170 Kanten, also alle Listen- und Referenzfälle
- **übersehen:** 0
- **unnötig bei Einbahnkanten:** Die Regel verwirft 22 Gegenrichtungen, die die Referenz ausgibt. Das sind die C-Fälle ohne Freigabe für die Gegenrichtung. Dort hat die Referenz in `ri=1` einen anderen Einrichtungsweg gematcht. Bei Oranienplatz, Rummelsburger Straße, Hauptstraße und Hardenbergplatz liegt die Gegenfahrbahn im Detailnetz parallel in 14–24 m Abstand. Das spricht für Fehler in der Referenz. Nachprüfen anhand einer Stichprobe.
- **behalten:** 36 Kanten, nämlich alle Kanten mit Freigabe für die Gegenrichtung oder mit Zweirichtungsweg in `ri=1`

Topologie hilft bei R/G nur ergänzend: Hat eine R-Kante einen Ring gleichen Namens, steht sie zu 44 von 48 in der Liste. Die Regel braucht dieses Merkmal nicht.

**Ergebnis 3: Die 17 B-Fälle lassen sich nicht verlässlich erkennen.** Es sind Platz-Ringe und Parkwege: Herrfurthplatz (4 Kanten), Müggelbergplatz (4), Birkenallee (2), Joachimstraße (2), Paul-Lincke-Ufer, Scharnweberstraße, Wuhlgartenweg (2) und Urbanpark.

- Bei B-Kanten mit TILDA-Einbahn stehen 11 in der Liste und 1.364 nicht. Die Referenz gibt bei diesen 1.364 Kanten in `ri=1` zu 48 % Radwege aus. Es sind überwiegend OSM-Richtungsfahrbahnen, die das Detailnetz nicht aufteilt, und dort sind beide Richtungen richtig.
- Mit Zwilling oder Ring dazu stehen 5 in der Liste und 42 nicht.

Eine automatische Regel würde viele richtige Gegenrichtungen löschen. Für diese Stellen ist die Korrektur im RVN der richtige Weg, also `verkehrsrichtung` auf R oder G setzen. Dann greift die Regel aus Stufe 1.

**Feldnamen für die Freigabe in Gegenrichtung:**

| Datensatz | Einbahn für Rad | Freigabe in Gegenrichtung |
|---|---|---|
| `TILDA Straßen Berlin.fgb`, `data-raw-tilda/roads.fgb` | `oneway ∈ {yes, yes_dual_carriageway}` | `oneway_bicycle = no` |
| `TILDA Routing Berlin.gpkg` (`routing`) | `oneway = yes` (gilt schon für Rad) | `oneway = no` und `oneway_motor = yes` |
| `TILDA Routing Streets Translated.fgb` | `tilda_oneway` | `tilda_oneway_bicycle = no` bzw. `routing_oneway_motor = yes` |

Im Map-Matching kommt die Freigabe bereits über `verkehrsri` an: Bei `oneway_bicycle = no` wird `Zweirichtungsverkehr` gesetzt, siehe `scripts/translate_attributes_tilda_to_rvn.py`, `determine_verkehrsri`. `TildaWay::oneway` ist dann `false`.

## 3. Lösungsansatz

Stufe 1 ist die Regel im Map-Matching. Stufe 2 wird nicht umgesetzt; die B-Fälle korrigiert das RVN (siehe Abschnitt 6).

### Stufe 1: Richtungsfahrbahn aus `verkehrsrichtung`

**Regel:** Hat eine Kante `verkehrsrichtung ∈ {R, G}`, wird nur `ri=0` ausgegeben. Davon gibt es eine Ausnahme.

**Ausnahme:** `ri=1` bleibt, wenn Radverkehr auf dieser Fahrbahn nachweislich auch in Gegenrichtung fährt. Als Nachweis zählen TILDA-Wege, die in `ri=1` gematcht sind und eine der folgenden Bedingungen erfüllen:

- Quelle `bikelanes` mit `verkehrsri = Zweirichtungsverkehr`, also ein Zweirichtungsradweg (Gruppe B in 2.4).
- Quelle `streets` mit `verkehrsri = Zweirichtungsverkehr` und demselben normalisierten Straßennamen wie die Kante. Das ist eine Einbahnstraße mit freigegebenem Radverkehr in Gegenrichtung (`oneway:bicycle=no`, im Routing-Netz `oneway=no` + `oneway_motor=yes`).

Wege aus `paths`, Straßen mit anderem Namen und Einrichtungs-Radwege zählen nicht. Ein Einrichtungs-Radweg in `ri=1` einer Richtungsfahrbahn gehört nach 2.4 meist zur Gegenfahrbahn (Gruppe C). Ob das immer stimmt, klärt die Prüfung in QGIS (Abschnitt 6, Frage 3). Ein Nachweis gilt erst ab einem Mindestanteil an der Kantenlänge, über `min_evidence_share` einstellbar, Startwert 0,5. Der Anteil verhindert, dass kurze Schnipsel an Kreuzungen die Gegenrichtung retten.

Die Regel ist allgemein, beruht auf einem amtlichen Attribut und kommt ohne Ortskenntnis aus.

Auf den alten Daten erkennt diese Regel alle Listenfälle bei R/G (siehe 2.4).

### Stufe 2 (nicht empfohlen): Richtungsfahrbahnen trotz `verkehrsrichtung = B`

Laut 2.4 ist das zu ungenau: 5 Treffer stehen 42 Fehlalarmen gegenüber. **Entschieden (16.10.2026):** Die B-Fälle werden im RVN korrigiert, über `data/rvn_korrekturen.csv` (siehe Abschnitt 6). Der ursprüngliche Vorschlag folgt zur Dokumentation.

Für die 17 B-Fälle: Eine B-Kante gilt als Richtungsfahrbahn, wenn **beide** Bedingungen gelten.

1. **Topologie:** Im RVN- oder Detailnetz gibt es eine alternative Verbindung mit demselben Straßennamen. Das ist eine zweite Kante zwischen denselben Knoten oder ein kurzer Ring über höchstens 3 Kanten mit insgesamt höchstens 3-mal der Kantenlänge.
2. **TILDA:** Die Fahrbahn auf `ri=0` ist zu mindestens 50 % `oneway = yes` oder `yes_dual_carriageway` ohne Freigabe für Radverkehr in Gegenrichtung.

Eine der beiden Bedingungen allein reicht nicht. Eine B-Kante, die in OSM nur Einbahn ist, bleibt unberührt.

Alles, was danach übrig bleibt, ist ein Fehler im RVN-Netz und wird dort korrigiert. Das korrigierte RVN liefert der Nutzer nach.

## 4. Umsetzungsschritte

1. **Konfiguration:** In `config/default.toml` einen Abschnitt `[assemble.carriageway_rule]` anlegen, die passende Struktur in `src/config.rs`. Felder:
   - `enabled`
   - `oneway_values` (Standard `["R", "G"]`)
   - `min_evidence_share`
   - `evidence_ways`: Prädikate wie in der Regel-Engine (`Predicate`), dazu ein Flag für den Namensabgleich
2. **Regel in `src/assemble/mod.rs`:** In `Assembler::edge` vor der bestehenden Einbahn-Regel prüfen. Ist die Kante eine Richtungsfahrbahn und reicht der Nachweis nicht, `dirs[1]` leeren. Der Zähler kommt in `AssembleOutput` und `stats.json` (`carriageway_edges`).
3. **Zusammenspiel mit der Einbahn-Regel:** Die neue Regel läuft zuerst. Die bestehende Regel (oder die aus dem Regel-Patch, falls übernommen) bleibt für B-Kanten zuständig. Doppeltes Entfernen ist ausgeschlossen, weil `dirs[1]` danach leer ist.
4. **Debug:** In `src/debug.rs` für betroffene Kanten den Grund ausgeben, also `verkehrsrichtung`, Nachweisanteil und entfallen ja oder nein. So sind die Entscheidungen in QGIS nachvollziehbar.
5. **Unit-Tests** in `src/assemble/mod.rs`:
   - R-Kante, `ri=1` nur mit Gehweg-Schnipseln → `ri=1` entfällt.
   - R-Kante mit Zweirichtungsradweg über 80 % → `ri=1` bleibt.
   - R-Kante mit Einrichtungs-Radweg in `ri=1` → `ri=1` entfällt.
   - R-Kante mit Zweirichtungs-Fahrbahn gleichen Namens → `ri=1` bleibt.
   - R-Kante mit Zweirichtungs-Fahrbahn anderen Namens → `ri=1` entfällt.
   - B-Kante → unverändert.
6. **Lauf und Auswertung** (Berlin und Neukölln) gegen `snapping_network_enriched`, wie bisher:
   - `fuehr`-Übereinstimmung vor und nach der Änderung
   - Anzahl der Richtungen „nur im Ergebnis“ und „nur in der Referenz“
   - Diagnose aufgeschlüsselt nach `verkehrsrichtung` und nach Eintrag in der manuellen Liste. Die Liste dient dabei nur zur Erklärung der Abweichungen und fließt nicht ins Verfahren ein.
7. **Durchsicht der strittigen Kanten:** Die 22 Kanten mit `pruefen` (Gruppe C) im QGIS-Projekt ansehen. Das Ergebnis kommt als Tabelle in dieses Dokument.
8. **Akzeptanz:**
   - `42530048_42530044.02` hat nur `ri=0`.
   - „Nur im Ergebnis“ sinkt deutlich, „nur in der Referenz“ steigt nicht unerklärt.
   - `fuehr` sinkt nicht.

## 5. Nicht Teil dieses Plans

- Den HMM-Zustandsraum ändern, also `ri=1` von R-Kanten gar nicht erst als Zustand zulassen. Das würde zwar auch Folgefehler auf Nachbarkanten vermeiden, ändert aber das Matching selbst. Es kommt erst in Frage, wenn die Auswertung solche Folgefehler zeigt.
- Die Modi „Gegenrichtung“, „Hinrichtung“ und „Beide“ der alten Liste nachbilden.

## 6. Entscheidungen und offene Fragen

1. **Einfache Einbahnstraße (entschieden 16.10.2026):** `ri=1` entfällt. „Keine Radinfrastruktur vorhanden“ wird nicht ausgegeben.
2. **B-Fälle (umgesetzt 16.10.2026):**
   - **Liste:** Die 17 B-Kanten und eine RVN-Kante ohne Detailnetz (`55560007_56560038.02`) stehen in `data/rvn_korrekturen.csv`.
   - **Anwendung:** `scripts/enrich_rvn_with_detailnetz.py` wendet die Liste am Ende an (`apply_rvn_corrections`) und dreht dabei die Geometrie, wenn eine Kante von oder nach G wechselt.
   - **Richtung:** Sie folgt der OSM-Einbahnrichtung. Zwei Kanten am Müggelbergplatz (`59430029_59430035.02`, `59430034_59430029.02`) laufen gegen die Digitalisierung und bekommen G. Die alte Liste hatte dort die falsche Richtung behalten.
   - **Erweiterbar:** Die Liste nimmt weitere Sonderfälle auf. Neue Attribute müssen in `apply_rvn_corrections` freigeschaltet werden.
3. **C-Fälle (offen, Prüfung durch den Nutzer):**
   - **Was:** 22 R/G-Kanten, bei denen die Referenz in `ri=1` einen anderen Einrichtungsweg hat.
   - **Werkzeug:** QGIS-Projekt `processing/qgis/Einrichtungsfahrbahnen Prüfung.qgz`, erzeugt mit `qgis/erzeuge_einrichtungsfahrbahnen_projekt.py`. Es hat Lesezeichen je Kante. Ist die Referenz dort richtig, braucht die Regel eine weitere Ausnahme.
4. **Regel-Patch (offen):** Soll `docs/zwischenstand/agent_rules.patch` vorher übernommen werden? Dann baut Stufe 1 auf seiner `oneway_rule` auf statt auf der Regel in `main`.
