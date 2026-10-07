# MapRoulette: Radwege an der Mittellinie

`extract_centerline_tracks.py` erzeugt die Aufgabenliste für eine MapRoulette-Kampagne: Radwege im Seitenraum entlang des REN+-Netzes, die in OSM an der Straßen-Mittellinie erfasst sind (z. B. `cycleway:right=track`) und separat nachgezeichnet werden sollen.

```bash
python maproulette-centerline-tracks/extract_centerline_tracks.py
```

Optionen: `--buffer` (Puffer um das Netz, Standard 25 m), `--min-share` (Mindestanteil der Weglänge im Puffer, Standard 0.5), `--simplify` (Toleranz der Vereinfachung, Standard 1 m).

## Eingangsdaten

Der Ordner ist unabhängig von der restlichen Pipeline. `data/` ist nicht versioniert und enthält Symlinks:

| Datei | Inhalt |
|---|---|
| `data/bikelanes.fgb` | TILDA-Export `bikelanes` für Berlin |
| `data/ren_netz_gesamt.gpkg` | Vereinheitlichtes REN+-Netz (Layer `ren_netz`); verwendet wird nur das Kartierungs-Netz (`bearbeitet_2025 = nein`) |

## Ablauf

1. **Filter auf transformierte Geometrien.** TILDA leitet für an der Straße erfasste Radwege eine eigene Geometrie ab (Hinweis „Transformierte Geometrie“ im Inspektor), erkennbar am Attribut `prefix`.
   - `prefix = cycleway` mit Kategorie `cycleway_adjoining`, `footAndCyclewaySegregated_adjoining` oder `footAndCyclewayShared_adjoining`
   - `prefix = sidewalk` mit Kategorie `footwayBicycleYes_adjoining` oder `footAndCyclewayShared_adjoining`, nur wenn ein Verkehrszeichen erfasst ist
   - Nicht enthalten: Führungen auf der Fahrbahn, geschützte Radfahrstreifen, Kreuzungsstücke
   - Nicht enthalten: unbeschilderte Radwege (ohne Z 237, 240, 241), wenn auf derselben Seite desselben OSM-Wegs eine Busspur mit Radfreigabe erfasst ist. Wie im Abgleich 2025 gewinnt dann die Busspur. Das trifft nur selten zu, weil Busspur und Radweg an der Mittellinie meist nicht gleichzeitig erfasst sind.
2. **Filter auf das Netz.** Wege, die zum Mindestanteil im Puffer um das Netz liegen.
3. **Gruppierung.** Wege mit gleichem Straßennamen, die über gemeinsame Endpunkte zusammenhängen, bilden eine Gruppe. Linke und rechte Seite einer Straße liegen in derselben Gruppe.
4. **Versatz.** Die Geometrie wird um `offset` (halbe Straßenbreite, + links / − rechts) von der Mittellinie zur Seite versetzt und vereinfacht. Linke Seiten laufen danach gegen die OSM-Richtung, also in Fahrtrichtung.

## Ausgabe

Jeder Lauf schreibt in einen eigenen Ordner `output/<Datum>/`, frühere Läufe bleiben erhalten. So lässt sich nach ein paar Wochen vergleichen, was übrig ist. `public/` enthält eine Kopie des letzten Laufs für Netlify. Beide Ordner sind nicht versioniert.

| Datei | Inhalt |
|---|---|
| `centerline_tracks.geojson` | Alle Wege mit den TILDA-Attributen, `side` und `group`, zur Vorschau |
| `centerline_tracks_maproulette.json` | Zeilenweises GeoJSON für MapRoulette wie in der TILDA-API: pro Zeile ein Record-Separator und eine FeatureCollection, eine Zeile pro Gruppe |
| `centerline_tracks_stats.json` | Anzahl und Länge je Kategorie, Kennzahlen zu den Gruppen (nur in `output/<Datum>/`) |

Liegen auf einer Seite eines OSM-Wegs Radweg und Gehweg an der Mittellinie, gibt es dafür nur eine Linie.

Die Kennung einer Aufgabe ist die `id` ihres ersten Features, also der OSM-Weg mit der kleinsten id in der Gruppe (`way/123`). Der Aufgabentext (`task_markdown`) mit Link in den Editor und der Liste der OSM-Wege steht ebenfalls am ersten Feature.

## Veröffentlichen

Die MapRoulette-Datei liegt auf Netlify, damit sie sich nach einem neuen Lauf aktualisieren lässt.

```bash
# Einmalig: Netlify-Projekt anlegen und mit diesem Ordner verknüpfen
netlify sites:create
# Nach jedem Lauf
netlify deploy --prod
```

`challenge.json` beschreibt die Challenge so, wie sie an die MapRoulette-API geht. Vor dem ersten Push `parent` (Projekt-ID) und `remoteGeoJson` (Netlify-URL der Datei `centerline_tracks_maproulette.json`) eintragen.

```bash
# Legt die Challenge an oder aktualisiert sie und liest die Aufgaben neu ein
MAPROULETTE_API_KEY=... ./push_challenge.sh
```

Beim Anlegen schreibt das Skript die neue `id` in `challenge.json`. Beim Neu-Einlesen entfernt MapRoulette offene Aufgaben, die nicht mehr in den Daten sind.
