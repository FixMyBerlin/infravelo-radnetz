# Backlog: Datensatz C aus dem Radnetz-Graphen

Offene Vorhaben der Pipeline (README.md). Neue Punkte oben anfügen.

## Kandidaten über die Zuordnung des HMM verketten (Radweg → Straße → RVN)

**Stand:** `sql/105` legt die Kandidaten einer Straßenkante (Straße selbst, Seitenobjekte, gefaltete Radwege) auf das
RVN. Kandidaten über die ganze Straßenkante übernehmen die gematchten Abschnitte der Kante unverändert (seit `f688926`).
Teilstücke (Faltung nur über einen Teil der Kante) werden noch geometrisch projiziert: Anfangs- und Endpunkt auf der
Straße per `ST_LineLocatePoint` auf die RVN-Kante. Knickt die Straßenkante ab (z. B. um eine Ecke auf zwei RVN-Kanten),
landet ein Endpunkt seitlich der RVN-Kante, und der Kandidat verliert einen Teil (Großer Stern, Spreeweg: 48,3 statt
55,9 m, vor `f688926`).

**Vorhaben:** die Zuordnung durchgehend verketten: Punkt auf dem Radweg → Punkt auf der Straße (Faltung, `bl_faltung`)
→ Punkt auf dem RVN (Viterbi).

1. Matcher (Rust): je Paar aufeinanderfolgender Beobachtungen eines Straßen-Traces ein Segment ausgeben, Lage auf der
   Straßenkante (m von bis) und auf dem RVN (Kante, Richtung, m von bis), mit Trace und Weg, als eigene Tabelle (z. B.
   `bikegraph.dc_iv_raw_obs`). Die Intervalle entstehen schon heute aus diesen Paaren (`hmm/mod.rs`), die Straßenseite
   geht beim Verdichten nur verloren.
2. Zusätzliche Beobachtungen an Kandidatengrenzen: `sql/104` gibt je Straßenkante die Lagen mit, an denen Kandidaten
   beginnen oder enden (Grenzen aus `bl_faltung`); die Trace tastet dort zusätzlich zum 5-m-Abstand ab. Jede
   Kandidatengrenze hat dann eine eigene Beobachtung mit exakter RVN-Lage.
3. `sql/105`: Kandidat über die Straßenmeter a..b = alle Segmente zwischen den Beobachtungen bei a und b, also deren
   RVN-Abschnitte; ersetzt die geometrische Projektion und den Sonderfall „ganze Kante“.

**Grenzen:** HMM-Brüche und Null-Zustand lassen Lücken (richtig, dort ist die Straße nicht gematcht); innerhalb eines
gerouteten Schritts zwischen zwei Beobachtungen wird linear interpoliert; falsche HMM-Entscheidungen gehen direkt in
die Kandidaten. **Prüfen:** Variante gegen den aktuellen Stand und gegen die Baseline auf denselben Daten.

## Weitere offene Punkte

- **Plausibilität der Faltung:** Faltungen ohne Radwegteil fallen seit `5201043` weg; offen sind Längenverhältnis
  Straße/Radweg (Läufe ab 10 m außerhalb 0,67–1,5, darunter nur starke Ausreißer), Abstand über 25 m, Winkel über 45°.
- **Querungen (`crossing`):** ob sie überhaupt gefaltet werden sollen oder wie die isolierten Radwege direkt in den
  RVN-Schritt gehen.
- **Breite in der Aggregation:** kleinste Breite aller Stücke, gleich welcher Führungsform; Vorschlag: nur Stücke der
  gewinnenden Führungsform. Dabei Mischverkehr: `normalize_mischverkehr_types` entfernt die Breite vor statt nach der
  Aggregation (`processing/start_aggregation.py`, betrifft auch die Baseline).
- **Aggregation zu lokal:** längste Führungsform je Kante nach Metern; Spurqualität (lange Trace ohne HMM-Bruch) zählt
  nicht. Ideen: Lücken mit schwächeren Kandidaten zwischen gleichen stärkeren Gewinnern schließen, Gewichtung nach
  Trace-Länge und Brüchen.
- **Tunnel:** aus dem Straßennetz ausgeschlossen; Lücken wie Gleimtunnel, Eichkampstraße. Optionen: Tunnel nur aus der
  Faltung nehmen, nur kurze oder nur Tunnel ohne parallele Straße oben ausschließen.
- **HMM-Brüche durch Knicke ohne Abzweigung:** mit `KNICK_OHNE_ABZWEIG=true` (Standard seit v7) steigen die Brüche im
  RVN-Matching von 557 auf 830; Martin-Ebene `strassen_traces` (rot) ansehen, ob bestimmte Knicke (z. B. Wenden am
  Ende von Sackgassen) ausgenommen werden sollten.
- **Vergleichsregeln (`sql/70_compare_c.sql`):** Regel 4 „Rang“ eher „unklar“; Regel 2 „Lage“ relativ statt fester 20 m.
- **Doppelte RVN-Kanten:** übereinanderliegende Kanten bekommen eine Trace nur einmal; Intervalle auf überlappende
  Kanten kopieren.
- **Daten-QA:** Straßen mit `bicycle=use_sidepath` ohne befahrbaren Weg daneben (z. B. Großer-Stern-Ring: daneben nur
  ein Gehweg ohne Radfreigabe).
