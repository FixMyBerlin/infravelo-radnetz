# Validierung

Prüft die Abgabedatensätze, bevor sie abgegeben werden. Jede Prüfung meldet: bestanden oder nicht, wie viele Verstöße bei wie vielen geprüften Objekten, und welche Objekte betroffen sind. Jeder Lauf wird gespeichert. Zwei beliebige Läufe lassen sich direkt vergleichen.

Die Validierung liest nur die fertigen Dateien und läuft unabhängig von der Prozessierung.

## Aufruf

Aus `processing/`:

```bash
./run_validation.sh --netz ren                      # alle Prüfungen, Lauf speichern
./run_validation.sh --netz rvn --clip neukoelln
./run_validation.sh --output-dir output-last-run    # anderen Ordner mit Abgabedateien prüfen
./run_validation.sh --nur B- VK-                    # nur Prüfungen, deren ID so beginnt
```

Exit-Code 1, sobald eine Prüfung mit Schwere *fehler* Verstöße hat oder nicht laufen konnte (z. B. Eingabe fehlt). Warnungen ändern ihn nicht.

### Läufe vergleichen

```bash
./run_validation.sh list                  # alle Läufe mit Nummer
./run_validation.sh diff                  # fragt nach zwei Läufen, danach nach Details einzelner Prüfungen
./run_validation.sh diff 3 7              # Lauf #3 gegen #7 – die Läufe dazwischen spielen keine Rolle
./run_validation.sh diff -2 -1            # vorletzter gegen neuesten
./run_validation.sh diff 3 7 --check B-NULL --limit 0   # alle neuen und behobenen Verstöße
./run_validation.sh history -n 15         # Anzahl Verstöße je Prüfung über die letzten 15 Läufe
./run_validation.sh show 7                # Übersicht eines gespeicherten Laufs
```

Der Diff zeigt je Prüfung die Anzahl in beiden Läufen, Δ, **neu** (Verstöße nur im zweiten Lauf) und **behoben** (nur im ersten). Daran sieht man auch Änderungen bei gleicher Anzahl, etwa 5 neu und 5 behoben. Er zeigt außerdem, welche Eingabedateien sich zwischen den Läufen geändert haben (Hash). Unveränderte Prüfungen fasst er in einer Zeile zusammen.

## Ausgabe eines Laufs

Oben steht die Übersicht, gruppiert nach Datensatz: eine Zeile je Prüfung mit Status, Anzahl Verstöße (Paare Objekt + Detail, z. B. Attribut), betroffene Objekte / geprüfte Objekte, Anteil und der Veränderung zum letzten Lauf derselben Variante (Netz + Zuschnitt), z. B. `+3 −8`. Darunter folgen Details nur für nicht bestandene Prüfungen: Regel, Verteilung nach Detail (z. B. Attribut) und einige Beispiele.

## Ablage der Läufe

```
validation/runs/20261118-143012_ren/
    run.json              Netz, Zuschnitt, Commit, Eingaben (Pfad, Größe, Hash, Objekte), Ergebnis je Prüfung
    verstoesse/<ID>.csv   alle Verstöße einer Prüfung (objekt, detail), sortiert
    verstoesse.gpkg       ein Layer je Prüfung mit Geometrie, zum Ansehen in QGIS
```

`runs/` ist nicht im Git, die Läufe bleiben lokal. Die CSVs lassen sich auch direkt mit `diff` vergleichen.

## Datensätze und Schlüssel

| Kürzel | Datensatz | Datei | Schlüssel eines Objekts |
|---|---|---|---|
| B | Radverkehrsanlagen | `output/snapping_converted_bikelanes{_ren}{_clip}.fgb` | `element_nr ri=… tilda_id` |
| C | Aggregiertes Netz | `output/aggregated_rvn_final{_ren}{_clip}.gpkg` (beide Layer) | `element_nr ri=…` |
| K | Knotenpunkte, Abgabestand | `knotenpunkte/output/knotenpunkte_abgabe.gpkg` (Projekt-Root, unabhängig von `--output-dir`) | `Knotenpunkt‐ID` |
| VK | Virtuelle Knotenpunkte | `netzanpassungen/output/virtuelle_knoten.gpkg` (Projekt-Root, Schritt 3; dazu das Archiv der 53 von 2025 in `netzanpassungen/one_time_import/2025/`) | Nummer |

Der Diff braucht Schlüssel, die über Läufe gleich bleiben. Zeilennummern wie `afid`, `sfid` oder der Index ändern sich bei jeder Prozessierung und taugen deshalb nicht. Kommt ein Schlüssel mehrfach vor, wird er nach Lage mit `#2`, `#3` … ergänzt. In B ist das üblich: Ein TILDA-Weg kann auf derselben Kante in mehreren getrennten Stücken liegen, z. B. wenn ein Teil an einer Kreuzung zu „Kreuzungsweg (Konvertiert)“ wird.

## Neue Prüfung anlegen

In einem Modul unter `checks/` (neues Modul in `checks/__init__.py` eintragen):

```python
from ..framework import WARNUNG, Ergebnis, pruefung, verstoesse

@pruefung("FAHRRADSTRASSE-BREITE", "Fahrradstraße höchstens 8 m breit", datensaetze=["B", "C"],
          regel="fuehr = Fahrradstraße → breite ≤ 8.")
def fahrradstrasse_breite(ctx, ds):
    gdf = ctx.datensatz(ds)                     # geladen mit Spalte _key, einmal je Lauf
    fs = gdf[gdf["fuehr"] == "Fahrradstraße"]
    return Ergebnis(geprueft=len(fs), verstoesse=verstoesse(fs, fs["breite"] > 8, "breite"))
```

- Die ID wird `<Datensatz>-<slug>`, hier `B-FAHRRADSTRASSE-BREITE` und `C-FAHRRADSTRASSE-BREITE`.
- `schwere=WARNUNG` für Prüfungen, die den Exit-Code nicht ändern sollen.
- `detail` ist ein fester Text oder eine Series. Er sollte über Läufe stabil sein, also z. B. das Attribut und nicht ein Messwert, sonst erscheint jede kleine Änderung als „neu“ und „behoben“.
- Weitere Eingabedateien mit `ctx.eingabe(name, pfad)` öffnen. Damit stehen sie in den Metadaten und der Diff erkennt Änderungen.

Geplante Prüfungen: [VALIDIERUNG_OFFEN.md](VALIDIERUNG_OFFEN.md).

## Aufbau

| Datei | Inhalt |
|---|---|
| `cli.py` | Kommandos `run`, `list`, `show`, `diff`, `history` |
| `framework.py` | `@pruefung`, `Ergebnis`, Ausführung und Status |
| `datasets.py` | Datensätze laden, Schlüssel, Fingerabdruck der Eingaben |
| `store.py` | Läufe speichern und laden |
| `report.py` | Ausgabe im Terminal |
| `checks/` | die Prüfungen |

Die Skripte `analyse_*.py`, `analyze_*.py` und `debug_*.py` in diesem Ordner sind Auswertungen für die Analyse und keine Prüfungen.
