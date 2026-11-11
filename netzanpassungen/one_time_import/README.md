# Einmalige Übernahme in die App Netzanpassungen

Dieser Ordner enthält Dateien, die **einmal** in die App Netzanpassungen (KV-Datenbank) hochgeladen werden und danach archiviert sind. Die Pipeline liest diesen Ordner nie. Handarbeit lebt in der App; `apply_app_result.py` schreibt daraus alles, was die Pipeline braucht, nach `netzanpassungen/output/`.

Umgewandelt am 2026-11-11 aus den Altlisten und der Knotendatei von 2025. Hochgeladen wird im Schritt „Gebiet“ der App mit „Einträge einspielen“ (Gebiet Berlin). Danach ändert sich hier nichts mehr; wer eine Korrektur braucht, macht sie in der App.

| Datei | Inhalt | Herkunft |
|---|---|---|
| `altlisten_korrekturen.json` | 38 `edge_correction`-Einträge (`von_nutzer: "Altliste"`): `verkehrsrichtung` aus `rvn_korrekturen.csv` (18) und `opposite_edge_overwrite_element_nr.txt` (1, Modus `remove`, nur Detailnetz B → R) sowie 19 Ausschlüsse aus `ausschluss_element_nr.csv` (Tunnel Tiergarten, Autobahn-Zubringer). `kommentar` ist die Begründung der Liste | Die drei Listen wurden mit einem einmaligen Skript (nicht im Repo) umgewandelt und gelöscht |
| `virtuelle_knoten_2025.json` | 53 `virtual_node`-Einträge (`name` = Knotenpunkt-ID, `lngLat` in WGS84 mit 7 Nachkommastellen an der Originallage, `kommentar`). Den Trägerkanten-Bezug (`traeger`) bestimmt die App beim Einspielen selbst | `Virtuelle-Knotenpunkte.gpkg`, mit einem einmaligen Skript (nicht im Repo) umgewandelt |
| `Virtuelle-Knotenpunkte.gpkg` | Archiv der Knotendatei von 2025 (53 Punkte, Spalte `Knotenpunkt-ID`, EPSG:25833), bis 2026-11-10 in `data/` | verschoben aus `data/` |

Wo die virtuellen Knoten jetzt leben: in der App. `apply_app_result.py` schreibt sie (alle nicht gelöschten Einträge des Exports „alle Einträge“) nach `netzanpassungen/output/virtuelle_knoten.gpkg`; diese Datei lesen `processing/` und `knotenpunkte/` über `processing/helpers/virtuelle_knoten.py`. Fehlt sie, bricht das Skript ab und sagt, dass erst der Import laufen muss.
