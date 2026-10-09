# Befahrungsbedarf

Ermittelt die OSM-Wege (TILDA) entlang des REN+-Netzes, für die es keine ausreichend aktuellen Fotos gibt und die deshalb neu befahren werden müssen. Das Ergebnis wird im [befahrungs-tracker](https://github.com/FixMyBerlin/befahrungs-tracker) weiterverwendet.

Die Verarbeitung ist vom restlichen Projekt getrennt und kann jederzeit neu ausgeführt werden. Sie nutzt eigene Eingangsdaten in `befahrungsbedarf/data/`; `data/` und `data-raw-tilda/` des Hauptprojekts bleiben unberührt.

```bash
./befahrungsbedarf/download_data.sh
python befahrungsbedarf/build.py
```

## Stand des letzten Laufs

`build.py` aktualisiert diesen Abschnitt bei jedem Lauf. Nach einem neuen Lauf die README mit committen.

<!-- stand:start -->
| | |
|---|---|
| Lauf | 2026-10-09 |
| Mapillary-Fotos berücksichtigt | **2024-04-05** bis 2026-10-05 |
| OSM-Stand des Mapillary-Abgleichs | 2026-10-03 |
| TILDA-Export | bikelanes_2026-10-05.fgb |
| Netz | 1996.4 km |
| Wege am Netz | 39257 Wege, 3531.6 km |
| Befahrungsbedarf | 5854 Wege, 783.3 km |
| davon Priorität 1 / 2 / 3 | 140.5 / 294.5 / 348.3 km |
| Wegen Busspur mit Radfreigabe entfallen | 21 Wege, 3.3 km |
| Zwischen zwei Richtungsfahrbahnen entfallen | 116 Wege, 11.7 km |
| Strecken zum Befahren | 1705 Strecken, 769.6 km, Median 273 m |
| davon über Wege ohne Bedarf verbunden | 115 Strecken, 4.9 km ohne Bedarf |
| Strecken unter 30 m entfernt | 541 Strecken, 13.1 km |
| Strecken ohne Radinfrastruktur unter 100 m entfernt | 454 Strecken, 23.1 km |
| Strecken quer zum Netz entfernt | 21 Strecken, 1.0 km |
<!-- stand:end -->

Das Startdatum der Mapillary-Fotos wandert mit jedem Abgleich weiter (siehe [Fotos](#fotos)). Wir dürfen Fotos ab 2024 verwenden; liegt das Startdatum in 2024 oder später, ist das erfüllt.

## Eingangsdaten (`data/`, nicht versioniert)

| Datei | Inhalt | Herkunft |
|---|---|---|
| `ren_netz_gesamt.gpkg` | REN+-Netz; verwendet wird nur das Kartierungs-Netz (`bearbeitet_2025` nicht `ja`) | Ausgabe von [`ren-network/unify_networks.py`](../ren-network/README.md) |
| `bikelanes.fgb`, `roads.fgb`, `roadsPathClasses.fgb` | TILDA-Wege für die Berlin-Bounding-Box | TILDA-Export, `download_data.sh` |
| `tilda_export.json`, `ml_metadata.json`, `osm_metadata.json` | Datenstände | `download_data.sh` |

`download_data.sh` braucht den TILDA-API-Key: Umgebungsvariable `ATLAS_API_KEY` oder `ATLAS_API_KEY_PRODUCTION` aus der `.env` des tilda-geo Repos (`TILDA_GEO_REPO`, Standard `../tilda-geo`).

## Fotos

- **Mapillary**: TILDA-Attribut `mapillary_coverage` (`pano`, `regular` oder leer) aus dem [Mapillary-Abgleich von vizsim](https://github.com/vizsim/mapillary_coverage). Gezählt werden Sequenzen der letzten 30 Monate vor dem Verarbeitungstag (`freshness_lookback_months = 30` in dessen `config/default.toml`), das Fenster ist also rollierend. Die TILDA-Attributbeschreibung nennt noch „ca. 2 Jahre“, das ist veraltet. Ein Weg gilt als abgedeckt, wenn mindestens 60 % seiner Länge im 10-m-Puffer einer Sequenz liegen. Ein Aufnahmedatum je Weg gibt es nicht.
- **Kfz-Befahrung 2025**: Fotos aller öffentlichen Straßen aus einer anderen Quelle. Dazu gibt es keinen Datensatz; die Sichtbarkeit wird aus den TILDA-Attributen abgeleitet (siehe Regeln).

## Ablauf

1. **Laden** der drei TILDA-Layer. Wege, die in mehreren Layern stehen, werden einmal übernommen (bikelanes vor roads vor roadsPathClasses).
2. **Wege am Netz**: Ein Weg bleibt, wenn mindestens 50 % seiner Länge im Puffer um die Netzkanten liegen (Pufferbreiten siehe unten). Wege unter 20 m entfallen. Die Richtung wird hier nicht geprüft; Strecken quer zum Netz entfallen erst nach dem Verbinden (siehe [Strecken](#strecken)).
3. **Netzattribute** der Kante, die dem Wegmittelpunkt am nächsten liegt.
4. **Klassifizierung** nach den Regeln unten, danach die Busspur-Regel und die Regel für Wege zwischen zwei Richtungsfahrbahnen.
5. **Strecken**: Wege mit Bedarf werden zu möglichst langen, geraden Strecken verbunden, kurze Reste entfallen (siehe [Strecken](#strecken)).
6. **Ausgabe** als GeoJSON (WGS84), Geometrie mit 1 m Toleranz vereinfacht.

Die Stellschrauben (`BUFFER_M_BY_CLASS`, `MIN_SHARE`, `MIN_LENGTH_M`, `SIMPLIFY_M`) und die Regel-Listen stehen oben in `build.py`.

### Pufferbreite je Straßenklasse

| `strassenklasse` der Netzkante | Puffer |
|---|---|
| I (und 0) | 22 m |
| II | 20 m |
| III | 15 m |
| IV | 12 m |
| V | 10 m |
| ohne Klasse (nicht im Detailnetz, meist eigenständige Wege) | 10 m |

Die Breiten sind gemessen: Sie decken je Klasse rund 95 % der TILDA-Radwege im Seitenraum ab (Abstand zur Netzkante). Ein einheitlicher 25-m-Puffer hatte an kleinen Straßen zu viele Wege erfasst, die nur in der Nähe liegen.

## Regeln

### `kfz_bild`: Sichtbarkeit auf den Kfz-Befahrungsfotos

| Wert | Wege |
|---|---|
| `ja` | Öffentliche Straßen (roads), Führungen auf der Fahrbahn (`cyclewayOnHighway*`, `sharedBusLane*`, `sharedMotorVehicleLane`, `bicycleRoad*`), Querungen |
| `unsicher` | Führungen im Seitenraum (`*_adjoining`, `*_adjoiningOrIsolated`, `cyclewayLink`, `needsClarification`): Sicht hängt von parkenden Fahrzeugen ab |
| `nein` | Privatstraßen und -wege (`operator_type=private`), `service_*`, `pedestrian`, `track`, eigenständige Führungen (`*_isolated`, `pedestrianAreaBicycleYes`), alle übrigen Wege aus roadsPathClasses |

### `bedarf` und `prioritaet`

| `bedarf` | `prioritaet` | Bedingung |
|---|---|---|
| `nein` | – | `kfz_bild=ja` oder `mapillary_coverage=pano` |
| `ja` | 1 | `kfz_bild=nein` und keine Mapillary-Fotos |
| `ja` | 2 | `kfz_bild=unsicher` und keine Mapillary-Fotos |
| `ja` | 3 | nur Mapillary-Fotos ohne Panorama (`regular`) |

### Busspur mit Radfreigabe

Wie im Abgleich 2025 gewinnt eine Busspur mit Radfreigabe (`sharedBusLane*`) gegen einen unbeschilderten Radweg daneben: Die Busspur wird erfasst, der Radweg muss nicht befahren werden (`bedarf = nein`, `grund = Busspur mit Radfreigabe`).

- **Radweg**: `cycleway_adjoining*`, `cycleway_isolated`, `footAndCyclewayShared*`, `footAndCyclewaySegregated*` ohne Z 237, 240 oder 241 in `traffic_sign`.
- **An der Mittellinie erfasst**: dieselbe Seite desselben OSM-Wegs wie die Busspur.
- **Separat erfasst**: mindestens 80 % des Radwegs liegen in Fahrtrichtung rechts der Busspur, höchstens 20 m von der Straßen-Mittellinie entfernt und höchstens 30° dazu gedreht. Der Straßenname wird nicht verglichen, weil separate Wege oft keinen tragen.

Wird später mehr Beschilderung erfasst, entfallen weniger Wege.

### Zwischen zwei Richtungsfahrbahnen

Bei getrennten Richtungsfahrbahnen liegt die Radinfrastruktur außen. Ein Weg ohne Radinfrastruktur auf dem Mittelstreifen muss deshalb nicht befahren werden (`bedarf = nein`, `grund = zwischen Richtungsfahrbahnen`). Beispiel: der Gehweg [way/1228388287](https://www.openstreetmap.org/way/1228388287) zwischen Engeldamm und Bethaniendamm.

Ein Weg entfällt, wenn alles zutrifft:

- Er hat keine Radinfrastruktur-Kategorie (Gehweg, Pfad, Zufahrt; Radwege auf dem Mittelstreifen bleiben).
- Mindestens 80 % seiner Länge liegen links einer Einbahn-Fahrbahn in seiner Richtung und links einer Einbahn-Fahrbahn in Gegenrichtung, jeweils höchstens 50 m entfernt und höchstens 30° dazu gedreht.
- Beide Fahrbahnen geben für ihre linke Seite ausdrücklich keine Radinfrastruktur an (TILDA `bikelane_left = data_no`).

Die Regel trifft auch Uferwege zwischen zwei Uferstraßen (z. B. am Landwehrkanal zwischen Schöneberger Ufer und Reichpietschufer).

## Strecken

`merge_lines.py` verbindet die Wege mit Bedarf, damit beim Befahren zusammenhängende Strecken statt vieler kurzer Stücke entstehen. Die Schwellen stehen oben im Skript.

1. **Auf die Straßenseite versetzen**: An der Mittellinie erfasste Radwege (`way/123/cycleway/left`) liegen in TILDA auf der Mittellinie, links und rechts also aufeinander. Sie werden um `offset` (halbe Straßenbreite) zur Seite versetzt, damit sichtbar ist, ob eine oder beide Seiten befahren werden müssen. Linke Seiten laufen danach in Fahrtrichtung.
1. **Fortsetzung suchen**: Zwei Wegenden werden verbunden, wenn das zweite in Verlängerung des ersten liegt: höchstens 40 m entfernt, höchstens 30° abgeknickt und höchstens 5 m seitlich versetzt (damit die Straßenseite nicht wechselt). 40 m reichen über eine Einmündung hinweg; mit 20 m blieb z. B. die Pallasstraße an jeder Einmündung getrennt.
2. **Eindeutig**: Jedes Ende wird nur einmal verbunden. Bei mehreren Kandidaten gewinnt die nächste und geradeste Fortsetzung.
2. **Brücken**: Kurze Wege ohne Bedarf (z. B. Querungen an Einmündungen) schließen eine Lücke zwischen zwei Wegen mit Bedarf, wenn sie zusammen höchstens 50 m lang sind. Eine direkte Fortsetzung mit Bedarf geht immer vor. `prioritaet_stats` nennt diese Kilometer als „ohne Bedarf“.
3. **Prioritäten**: Wege aller Prioritäten werden verbunden. Ausnahme: Ein zusammenhängendes Stück mit Priorität 3 ab 1 km oder mit Priorität 2 ab 2 km bleibt eine eigene Strecke. `prioritaet_stats` nennt die Kilometer je Priorität.
4. **Lücken** werden mit einer geraden Linie geschlossen, die Strecke wird danach vereinfacht.
5. **Kurze Reste**: Strecken unter 30 m entfallen, unabhängig von der Priorität.
6. **Quer zum Netz**: Strecken, die das Netz nur queren, entfallen. Eine Strecke läuft an einer Stelle entlang des Netzes, wenn sie dort höchstens 60° von der Richtung einer nahen Netzkante abweicht; liegt weniger als die Hälfte der Strecke entlang des Netzes, entfällt sie (`ALONG_*` in `build.py`).
7. **Ohne Radinfrastruktur**: Strecken, in denen kein Weg mit Bedarf eine Radinfrastruktur-Kategorie hat (reine Gehwege, Pfade, Treppen, Zufahrten), bleiben erst ab 100 m. Kürzere sind meist Verbindungsstücke, auf denen keine Radinfrastruktur zu erwarten ist.

Entfallene Strecken stehen mit dem Attribut `grund` in `entfernt.geojson`.

Attribute je Strecke:

| Attribut | Inhalt |
|---|---|
| `id` | Schlüssel aus erster und letzter OSM-ID und der Anzahl der Wege (`w123-w456-n7`). Linke und rechte Seite derselben Straße teilen sich die OSM-IDs; die zweite Strecke bekommt dann `-2` angehängt |
| `osm_ids` | OSM-IDs der Wege in Reihenfolge entlang der Strecke, durch Semikolon getrennt |
| `name` | Straßenname mit dem größten Längenanteil |
| `prioritaet` | Dringlichste Priorität der Wege (kleinste Zahl) |
| `prioritaet_stats` | Aufteilung, z. B. `3,05 km, davon 1,00 km Prio 1, 2,00 km Prio 2, 0,05 km ohne Bedarf` |
| `laenge_m`, `anzahl_teile` | Länge inkl. geschlossener Lücken, Anzahl der Wege |
| `befahrung_links_markdown` | Markdown-Links zur Mapillary-Abdeckung (Kartenmitte = Streckenmitte) und zum Routing (Streckenanfang bis -ende) |

Die übrigen Attribute je Weg stehen in `pruefung_einzelwege.geojson`.

## Ausgabe (`output/`, nicht versioniert)

| Datei | Inhalt |
|---|---|
| `befahrung_strecken.geojson` | Strecken zum Befahren: Wege mit `bedarf=ja`, verbunden |
| `entfernt.geojson` | Strecken, die nach dem Verbinden entfallen, mit `grund` (kürzer als 30 m, quer zum Netz, ohne Radinfrastruktur und kürzer als 100 m) |
| `befahrungsbedarf.geojson` | Einzelne Wege mit `bedarf=ja` |
| `pruefung_einzelwege.geojson` | alle Wege am Netz inkl. Klassifizierung |
| `statistik.json` | Kilometer je Klasse, Parameter und Datenstände |

Das Netz selbst als GeoJSON schreibt `ren-network/unify_networks.py` nach `ren-network/output/ren_netz_gesamt.geojson`.

Attribute je Weg:

| Attribut | Inhalt |
|---|---|
| `id`, `osm_id` | TILDA-ID (`way/123` oder `way/123/cycleway/left`) und OSM-ID |
| `quelle` | TILDA-Layer |
| `road`, `category`, `name`, `lifecycle`, `operator_type` | aus TILDA |
| `mapillary_coverage` | `pano`, `regular` oder leer |
| `anteil_am_netz` | Längenanteil im Netzpuffer (0.5–1) |
| `element_nr`, `radverkehrsnetz`, `strassenklasse`, `bezirksnummer`, `strassenname` | nächste Netzkante |
| `laenge_m` | Länge |
| `kfz_bild`, `bedarf`, `prioritaet`, `grund` | Klassifizierung |

`id` ist der eindeutige Schlüssel. `osm_id` ist es nicht: Eine Straße (`way/123`) und ihre Radwege links und rechts (`way/123/cycleway/left`, `way/123/cycleway/right`) teilen sich dieselbe OSM-ID.

## Entscheidungen

Stand 2026-10-06.

- **Eigener Ordner, eigene Daten**: Die Auswertung hängt fachlich am Projekt, soll aber unabhängig neu laufen können. Die TILDA-Daten des Hauptprojekts (`data/`, Stand 2025) bleiben vorerst unverändert.
- **Fotos ab 2024**: Das rollierende 30-Monats-Fenster des Mapillary-Abgleichs reicht dafür aus. Ein fester Stichtag 2024-01-01 wird nicht nachgerechnet.
- **Panoramen zählen, einfache Fotos nicht**: Nur `pano` gilt als abgedeckt. Wege mit `regular` bleiben mit niedrigster Priorität (3) im Bedarf, damit sie später ebenfalls befahren werden können.
- **Kfz-Befahrung 2025**: Befahren wurden öffentliche Straßen, keine Zufahrten, Wirtschaftswege oder Privatstraßen. Führungen direkt auf der Fahrbahn sind auf den Fotos sichtbar. Im Seitenraum (z. B. Hochbordradweg, gemeinsamer Geh- und Radweg) hängt die Sicht von parkenden Fahrzeugen ab, deshalb `unsicher` und Priorität 2.
- **Querungen** gelten als sichtbar, weil sie auf der Fahrbahn liegen.
- **Kaum Filter nach Wegeart**: Auch Gehwege, Pfade und Treppen bleiben enthalten. Dort kann neue Radinfrastruktur entstehen, z. B. ein neuer Radweg im Park.
- **Nur das Kartierungs-Netz**: Kanten, die 2025 schon bearbeitet wurden (Radvorrangnetz), entfallen seit 2026-10-07. Für sie liegen Fotos und Daten vor.
- **Autobahnen gehören nicht zum Netz**: Das Hauptstraßennetz enthält rund 230 km Autobahn und Zubringer. Sie werden seit 2026-10-06 schon in `ren-network/unify_networks.py` entfernt, damit alle Auswertungen dasselbe bereinigte Netz nutzen.
- **Puffer nach Straßenklasse** statt einheitlich 25 m, um Wege zu vermeiden, die nur neben der Straße liegen.
- **Wege unter 20 m entfallen**: Das war die Hälfte der Wege mit Bedarf, aber nur 9 % der Länge (vor allem kurze Gehwegstücke und Treppen).
- **Falsch-Positive sind in Ordnung**: Die Auswahl am Netz ist bewusst großzügig; unpassende Wege werden später gekürzt oder entfernt.
- **Keine Foto-Links im Datensatz**: Links zu Mapillary, Google Street View und Apple Look Around erzeugt der befahrungs-tracker.

## Offen

- Datum der letzten Aufnahme je Weg (bräuchte die Mapillary-API), bewusst zurückgestellt.
- Schwelle für die Auswahl am Netz (50 % im Puffer; eine niedrigere Schwelle bringt vor allem abzweigende Gehwege und Zufahrten).
- Das touristische Radnetz (Radfernwege) fehlt noch im Netz. Sobald es ergänzt ist, wächst das Netz und die Auswertung muss neu laufen.
