# Vergleich: unser HMM-Map-Matching und verkehr.nrw-osrm-matching

Stand: 09.11.2026. Grundlage: Code-Lektüre beider Projekte, ohne Build und ohne Testlauf.

- **Unser Projekt:** `processing/map-matching` (Rust). Ordnet TILDA-Wege dem Berliner Radvorrangnetz (RVN) bzw. REN+ zu.
- **Fremdes Projekt:** [Mobidrom/verkehr.nrw-osrm-matching](https://github.com/Mobidrom/verkehr.nrw-osrm-matching), Version 0.1.13 (Java, Quarkus, EUPL-1.2). Dekodiert OpenLR-Referenzen auf das OSM-Straßennetz.

Beide Projekte heißen „Map-Matching“, lösen aber verschiedene Aufgaben. Ein direkter Leistungsvergleich ergibt deshalb keinen Sinn. Dieses Dokument stellt die Ansätze nebeneinander und nennt, was sich übertragen lässt.

## 1. Aufgabe und Use Case

| | Unser Matching | verkehr.nrw-osrm-matching |
|---|---|---|
| Frage | Welche Radinfrastruktur aus OSM/TILDA liegt auf welcher Kante des Verwaltungsnetzes, je Richtung? | Welche OSM-Straße meint eine Verkehrsmeldung, die mit OpenLR kodiert ist? |
| Eingabe | Ganzes Netz: alle TILDA-Wege Berlins (bikelanes, streets, paths), rund 130.900 Kanten | Eine einzelne OpenLR-Linienreferenz (Base64-Binärform oder JSON „openlrExtendedLinear“) |
| Zielnetz | Eigenes, gerichtetes RVN-Detailnetz (`element_nr`, `ri`) | OSM-Straßennetz in einem OSRM-Server mit Profil `driving` |
| Ausgabe | FlatGeobuf, Kanten aufgeteilt in Abschnitte mit Führungsform, Breite, Oberfläche, `tilda_ids`, Konfidenz | JSON mit WKT-Geometrie, OSM-Node-IDs, Längen, Bearings, Status (`OK`, `OSRM_MATCHING_INPLAUSIBLE` …) |
| Betriebsart | Batch, mehrmals pro Datenstand | Online-Dienst (REST), pro Meldung ein Aufruf, Ergebnis wird in Postgres gecacht |
| Nutzer | Kartierungs- und Bearbeitungsstand des Berliner Radnetzes, Upload nach TILDA | Ökosystem von Verkehr.NRW (Landesagentur NRW.Mobidrom). Laut Helm-NetworkPolicy rufen nur Dienste aus dem Namespace `gf-argo-eventflows` auf; die Aufrufer selbst liegen nicht im Repo. |

**Use Case bei Mobidrom.** Externe Verkehrsdatenquellen liefern Meldungen (Staus, Baustellen, Sperrungen) mit OpenLR-Ortsreferenz. Das Paket `datex2` im Code deutet auf DATEX-II-Feeds hin; das ist aus dem Namen geschlossen, nicht belegt. Der Dienst übersetzt die Referenz in eine OSM-Geometrie und OSM-IDs, damit die Meldung auf der Karte von verkehr.nrw und in Routing-Diensten erscheinen kann.

**Use Case bei uns.** Das RVN ist ein amtliches Netz ohne aktuelle Attribute zur Radinfrastruktur. OSM bzw. TILDA hat die Attribute, aber eine andere Geometrie. Das Matching überträgt die Attribute auf das RVN, damit Bezirke und InfraVelo den Ausbaustand je Netzelement sehen.

## 2. Ablauf im Vergleich

### verkehr.nrw-osrm-matching

1. OpenLR-Binärstring dekodieren (Bibliothek `org.openlr` 1.4.3). Nur Linienreferenzen.
2. Aus den Location Reference Points (LRP) einen OSRM-`/match`-Request bauen: Koordinaten, `radiuses`, `bearings` (±30°), künstliche Zeitstempel bei 7 m/s, `gaps=ignore`, `annotations=true`.
3. Zuerst ein strenger Versuch. Prüfung: maximaler Abstand der Tracepoints 10 m und Längenfehler unter (n−1)·50 m gegenüber der OpenLR-Länge.
4. Scheitert er, folgen neun weitere Parametersätze aus einer festen Liste: andere Radien (2 m, 20 m), letzter Bearing ignoriert, zweiter OSRM-Server mit Gewichtung nach Distanz statt Zeit.
5. Aus den gültigen Ergebnissen gewinnt das mit dem kleinsten Score `2·maxTraceDist + |ΔLänge|`. Danach wird es mit 25 m Toleranz geprüft und als `OK` oder `OSRM_MATCHING_INPLAUSIBLE` markiert.
6. Positive und negative Offsets kürzen die Geometrie.
7. Ergebnis in `cache.openlr` speichern, Schlüssel ist Base64-String plus Länge.

Das eigentliche Matching (HMM) läuft in OSRM. Der Dienst steuert OSRM von außen und bewertet die Antworten.

### Unser Matching

1. Eigenen gerichteten Graphen aus dem RVN bauen (Knoten bei ≤1 cm zusammengefasst).
2. TILDA-Wege über die Topologie zu Traces verketten (gleiche Datenquelle, Abbiegewinkel ≤45°, Einrichtungswege nur vorwärts) und alle 5 m abtasten.
3. Kandidaten im R-Tree, Radius 30 m, höchstens 8 je Beobachtung, beide Richtungen jeder Kante.
4. Eigenes HMM: Emission aus Abstand (σ = 10 m), Richtungsabweichung, Seitenstrafe und Straßennamen. Übergang aus Differenz von Routen- und Trace-Distanz (β = 4 m), Dijkstra ohne Wenden. Zusätzlich ein Null-Zustand „liegt nicht auf dem RVN“.
5. Viterbi je Trace, parallel mit rayon.
6. Zuordnungen je Kante und Richtung in Abschnitte zerlegen, Konflikte über Regeln lösen (Rangfolge der Führungsformen, Lücken schließen, Kleinstücke verschmelzen), Einbahn-Regel, Bezirk zuordnen.
7. Evaluation gegen eine Referenz (das händisch geprüfte Ergebnis von 2025), längengewichtet.

## 3. Technische Unterschiede

| Thema | Unser Matching | verkehr.nrw-osrm-matching |
|---|---|---|
| Sprache, Laufzeit | Rust, CLI, GDAL | Java 25, Quarkus, Container in Kubernetes (Helm) |
| Matching-Kern | Eigenes HMM + Viterbi | OSRM `/match` (HMM in OSRM) |
| Netzmodell | Eigener Graph, gerichtete Kanten des Zielnetzes, Zweirichtungswege gespiegelt | OSRM-Graph aus OSM, Profil `driving`; Aufbau des OSRM-Netzes liegt außerhalb des Repos |
| Richtung | Kante plus `ri`, Einrichtungswege nur vorwärts | Bearings mit ±30° Toleranz, U-Turns werden als Fehler erkannt |
| Nicht passende Stücke | Null-Zustand im HMM, Lücken bleiben sichtbar | `gaps=ignore`, danach Plausibilitätsprüfung über Länge und Abstand |
| Robustheit | Ein Lauf mit festen Parametern | Bis zu zehn Läufe mit verschiedenen Parametern, Bestes gewinnt |
| Ergebnisqualität | Konfidenz je Kante (mittlere log-Emission), Regelname, Kandidatenzahl | Status-Enum je Meldung, Felder `valid`, `plausible`, `traceMaxDistance` |
| Konfiguration | `config/default.toml`, `--set`, Grid-Tuning (`tune`) | Schwellen als Konstanten im Code; nur Hosts sind konfigurierbar |
| Evaluation | Eigener Eval-Befehl mit KPIs, Konfusionsmatrix, Bezirksauswertung, `disagreements.fgb` | Keine Evaluation gegen Referenzdaten im Repo; ein CSV-Experiment (`OpenLRTest.java`) ohne Assertions |
| Debug | `--debug` schreibt Beobachtungen, Konflikte, Brüche; `debug-trace` schreibt das Viterbi-Gitter | Logging; OpenTelemetry eingebunden, Exporter abgeschaltet |
| Tests | 21 Unit-Tests, keine CI für Rust | 23 Tests mit WireMock-OSRM und Postgres-Devservice, CI mit Checkstyle, Dependabot |
| Persistenz | Dateien (FlatGeobuf) | Postgres/PostGIS-Cache, Flyway-Migration |
| Reproduzierbarkeit | Abhängig vom Datenstand (TILDA-Export, RVN), Daten nicht versioniert | Abhängig vom OSRM-Datenstand; Cache kennt den Datenstand nicht |

## 4. Prozess bei Mobidrom

Aus dem Repo erkennbar:

- Entwicklung auf GitHub, wiederverwendbarer CI-Workflow aus `mobidrom/github-actions` (auf `@main`, nicht auf einen Commit gepinnt). Die CI schreibt Versionen in Chart und `gradle.properties` zurück.
- Container-Image per Jib nach ghcr.io, Deployment per Helm in den Namespace `run-verkehr-nrw`, ein Replica, Health-Probes.
- Zwei OSRM-Server laufen als eigene Dienste (`osrm-router-openlr`, `osrm-router-distance`). Wie und wie oft deren OSM-Daten aktualisiert werden, steht nicht im Repo.
- Dependabot wöchentlich, Checkstyle ohne Warnungen.
- Zweisprachige Lizenztexte (EUPL-1.2, deutsch und englisch), Attribution für OSM und OSRM.

Nicht erkennbar: wer die Meldungen liefert, wie oft der Dienst aufgerufen wird, wie die Ergebnisqualität fachlich geprüft wird.

## 5. Was für uns interessant ist

1. **Statuswerte statt nur Konfidenz.** Ein Enum wie `OK / INPLAUSIBLE / FAILED` mit Grund (U-Turn, Längenfehler, keine Kandidaten) ist für Bearbeitende leichter zu lesen als ein log-Wert. Wir könnten aus `hmm_konfidenz`, HMM-Brüchen und Null-Zustand-Anteil einen Status je Kante ableiten.
2. **Längenvergleich als Plausibilitätsprüfung.** Die Prüfung „gematchte Länge gegen erwartete Länge“ ist einfach und fängt Umwege ab. Bei uns ließe sich die Summe der zugeordneten Trace-Länge mit der Kantenlänge vergleichen.
3. **Fallback-Kaskade.** Mehrere Parametersätze nacheinander und der beste gewinnt. Für uns denkbar bei Traces mit HMM-Bruch: ein zweiter Lauf mit größerem Radius oder ohne Namensstrafe, nur für die betroffenen Traces.
4. **Zweites Gewicht (Distanz statt Zeit).** Für uns weniger relevant, weil unser Dijkstra schon nach Distanz rechnet.
5. **CI und Tests mit Fixtures.** WireMock-Antworten als feste Testdaten entsprechen bei uns kleinen FlatGeobuf-Fixtures. Eine Rust-CI (`cargo test`, `clippy`) fehlt bei uns noch.
6. **OpenLR als Austauschformat.** Falls Berlin oder TILDA künftig Meldungen oder Abschnitte mit anderen Systemen austauscht, ist OpenLR ein netzunabhängiger Weg, Strecken zu referenzieren. Für das Radnetz gibt es aktuell keinen Bedarf.

## 6. Was wir anders machen

Neutral formuliert, jeweils mit dem Grund:

- **Eigenes HMM statt OSRM.** Unser Zielnetz ist das RVN, kein OSM-Netz. OSRM kann nur auf seinem eigenen Graphen matchen. Außerdem brauchen wir Fahrrad-spezifische Regeln (Seite der Fahrbahn, Einrichtungswege, Straßenname), die ein OSRM-Profil nicht abbildet.
- **Null-Zustand.** Viele TILDA-Wege liegen absichtlich nicht auf dem RVN. Das HMM kann „gehört nicht dazu“ ausdrücken. Bei OpenLR soll dagegen jede Meldung auf eine Straße passen, darum genügt dort Plausibilitätsprüfung.
- **Aufteilung von Kanten.** Wir zerlegen Kanten in Abschnitte mit verschiedenen Attributen und lösen Konflikte über Regeln. Der NRW-Dienst gibt eine durchgehende Linie zurück; Attribute spielen keine Rolle.
- **Evaluation gegen Referenz.** Wir messen die Qualität über das ganze Netz (Führungsform 92,2 % Übereinstimmung, Stand 15.10.2026). Der NRW-Dienst prüft jede Meldung einzeln, eine Gesamtbewertung ist im Repo nicht enthalten.
- **Konfigurierbarkeit und Debug.** Unsere Parameter liegen in einer TOML-Datei, es gibt Grid-Tuning und Debug-Layer. Im NRW-Dienst stehen die Schwellen als Konstanten im Code.
- **Betrieb.** Der NRW-Dienst hat CI, Container, Helm und Health-Checks, weil er dauerhaft läuft. Unser Matching ist ein Batch-Werkzeug ohne CI.

## 7. Auffälligkeiten im NRW-Code

Aus der Code-Lektüre, nicht getestet. Nützlich, falls wir Kontakt zu Mobidrom aufnehmen:

- Der Cache speichert auch Fehlerergebnisse (z. B. `OSRM_CONNECTION_ERROR`) dauerhaft und kennt keinen OSRM-Datenstand.
- Offsets kürzen die Geometrie interpoliert, die Node-IDs aber nur in ganzen Segmenten. Beide können auseinanderlaufen.
- Einige Statuswerte aus dem README (`FILTERED_BY_FRC_FILTER`, `OFFSET_ROUTING_FAILED`, `BYTE_STRING_DECODING_ERROR`) setzt der Code nie.
- Der Parameter `srid` am Endpunkt `/geometry` transformiert nicht; OSRM bekommt die Rohkoordinaten.
- Bis zu zehn OSRM-Aufrufe laufen nacheinander mit je 10 s Timeout.

## Quellen

- [Mobidrom/verkehr.nrw-osrm-matching](https://github.com/Mobidrom/verkehr.nrw-osrm-matching), vor allem `README.md`, `service/openlr/OpenLRValidator.java`, `service/api/openlr/OpenLRMatchingParameters.java`, `service/api/openlr/OpenLROsrmMatching.java`, `charts/values.yaml`
- [Pressemitteilung Land NRW zur Landesagentur NRW.Mobidrom](https://www.land.nrw/pressemitteilung/landesagentur-nrwmobidrom-sorgt-fuer-bessere-vernetzung-und-buendelung-von)
- Unser Projekt: [README.md](../README.md), [config/default.toml](../config/default.toml), [tilda-routing.md](tilda-routing.md)
