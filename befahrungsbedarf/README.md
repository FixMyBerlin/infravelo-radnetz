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
| Lauf | 2026-10-06 |
| Mapillary-Fotos berücksichtigt | **2024-04-05** bis 2026-10-05 |
| OSM-Stand des Mapillary-Abgleichs | 2026-10-03 |
| TILDA-Export | bikelanes_2026-10-05.fgb |
| Netz | 2872.6 km |
| Wege am Netz | 58798 Wege, 5218.6 km |
| Befahrungsbedarf | 8137 Wege, 1048.1 km |
| davon Priorität 1 / 2 / 3 | 185.3 / 332.9 / 529.9 km |
<!-- stand:end -->

Das Startdatum der Mapillary-Fotos wandert mit jedem Abgleich weiter (siehe [Fotos](#fotos)). Wir dürfen Fotos ab 2024 verwenden; liegt das Startdatum in 2024 oder später, ist das erfüllt.

## Eingangsdaten (`data/`, nicht versioniert)

| Datei | Inhalt | Herkunft |
|---|---|---|
| `ren_netz_vereinheitlicht.gpkg` | Netz, das befahren werden muss | Ausgabe von [`ren-network/unify_networks.py`](../ren-network/README.md) |
| `bikelanes.fgb`, `roads.fgb`, `roadsPathClasses.fgb` | TILDA-Wege für die Berlin-Bounding-Box | TILDA-Export, `download_data.sh` |
| `tilda_export.json`, `ml_metadata.json`, `osm_metadata.json` | Datenstände | `download_data.sh` |

`download_data.sh` braucht den TILDA-API-Key: Umgebungsvariable `ATLAS_API_KEY` oder `ATLAS_API_KEY_PRODUCTION` aus der `.env` des tilda-geo Repos (`TILDA_GEO_REPO`, Standard `../tilda-geo`).

## Fotos

- **Mapillary**: TILDA-Attribut `mapillary_coverage` (`pano`, `regular` oder leer) aus dem [Mapillary-Abgleich von vizsim](https://github.com/vizsim/mapillary_coverage). Gezählt werden Sequenzen der letzten 30 Monate vor dem Verarbeitungstag (`freshness_lookback_months = 30` in dessen `config/default.toml`), das Fenster ist also rollierend. Die TILDA-Attributbeschreibung nennt noch „ca. 2 Jahre“, das ist veraltet. Ein Weg gilt als abgedeckt, wenn mindestens 60 % seiner Länge im 10-m-Puffer einer Sequenz liegen. Ein Aufnahmedatum je Weg gibt es nicht.
- **Kfz-Befahrung 2025**: Fotos aller öffentlichen Straßen aus einer anderen Quelle. Dazu gibt es keinen Datensatz; die Sichtbarkeit wird aus den TILDA-Attributen abgeleitet (siehe Regeln).

## Ablauf

1. **Laden** der drei TILDA-Layer. Wege, die in mehreren Layern stehen, werden einmal übernommen (bikelanes vor roads vor roadsPathClasses).
2. **Wege am Netz**: Ein Weg bleibt, wenn mindestens 50 % seiner Länge im Puffer um die Netzkanten liegen (Pufferbreiten siehe unten). Wege unter 20 m entfallen. Die Richtung wird nicht geprüft, Querungen und kurze Stücke von Seitenstraßen bleiben also enthalten.
3. **Netzattribute** der Kante, die dem Wegmittelpunkt am nächsten liegt.
4. **Klassifizierung** nach den Regeln unten.
5. **Ausgabe** als GeoJSON (WGS84), Geometrie mit 1 m Toleranz vereinfacht.

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

## Ausgabe (`output/`, nicht versioniert)

| Datei | Inhalt |
|---|---|
| `befahrungsbedarf.geojson` | Wege mit `bedarf=ja` |
| `wege_am_netz.geojson` | alle Wege am Netz inkl. Klassifizierung |
| `statistik.json` | Kilometer je Klasse, Parameter und Datenstände |

Das Netz selbst als GeoJSON schreibt `ren-network/unify_networks.py` nach `output/ren-network/ren_netz_vereinheitlicht.geojson`.

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
- **Autobahnen gehören nicht zum Netz**: Das Hauptstraßennetz enthält rund 230 km Autobahn und Zubringer. Sie werden seit 2026-10-06 schon in `ren-network/unify_networks.py` entfernt, damit alle Auswertungen dasselbe bereinigte Netz nutzen.
- **Puffer nach Straßenklasse** statt einheitlich 25 m, um Wege zu vermeiden, die nur neben der Straße liegen.
- **Wege unter 20 m entfallen**: Das war die Hälfte der Wege mit Bedarf, aber nur 9 % der Länge (vor allem kurze Gehwegstücke und Treppen).
- **Falsch-Positive sind in Ordnung**: Die Auswahl am Netz ist bewusst großzügig; unpassende Wege werden später gekürzt oder entfernt.
- **Keine Foto-Links im Datensatz**: Links zu Mapillary, Google Street View und Apple Look Around erzeugt der befahrungs-tracker.

## Offen

- Datum der letzten Aufnahme je Weg (bräuchte die Mapillary-API), bewusst zurückgestellt.
- Schwelle für die Auswahl am Netz (50 % im Puffer; eine niedrigere Schwelle bringt vor allem abzweigende Gehwege und Zufahrten).
- Das touristische Radnetz (Radfernwege) fehlt noch im Netz. Sobald es ergänzt ist, wächst das Netz und die Auswertung muss neu laufen.
