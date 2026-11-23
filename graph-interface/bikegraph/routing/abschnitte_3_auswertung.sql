-- Routing der RVN-Abschnitte, Teil 3 (abschnitte.sh): Nähte, Gabelungen, Abschnittsmitten, Kreuzungsstücke, Projektion
-- auf das RVN und Ergebnis, aus den Wegen von Teil 2 (Regeln im Kopf von abschnitte_1_vorbereitung.sql).
-- Läuft mehrfach (abschnitte.sh: vor und nach dem Glätten, abschnitte_2b_glaetten.sql), deshalb zuerst die eigenen
-- Tabellen löschen.
-- psql-Variablen: schema, kreuzung_anteil (Standard 0.1, siehe Ergebnis), abstimmung (Standard stelle, siehe Ergebnis),
-- kreuzung_alle (Standard true, siehe Projektion), ganze_routen (Standard true, siehe Projektion),
-- gabel_durchgehend (Standard aus, siehe stimme)
\if :{?schema} \else \set schema routing_abschnitte \endif
\if :{?gabel_durchgehend} \else \set gabel_durchgehend aus \endif
\if :{?kreuzung_alle} \else \set kreuzung_alle true \endif
\if :{?ganze_routen} \else \set ganze_routen true \endif
\if :{?kreuzung_anteil} \else \set kreuzung_anteil 0.1 \endif
\if :{?abstimmung} \else \set abstimmung stelle \endif
SET search_path TO :"schema", public;
DROP TABLE IF EXISTS rolle, gabelung, naht, durchfahrt, grenze, abschnitt_pfad, abschnitt_route, kreuzung_pfad, kreuzung_route,
    rvn_stuecke, ergebnis;

CREATE INDEX IF NOT EXISTS pfad_rid_seq ON pfad (rid, seq);
CREATE INDEX IF NOT EXISTS pfad_rid_node ON pfad (rid, node);
ANALYZE pfad;

-- 3. Naht je Abschnitt
-- Routen je Abschnitt im Gebiet: ankommend (y = s) und abgehend (x = s); "allein" fehlt eine Seite, nimmt es ihre Rolle
CREATE TABLE rolle AS
WITH r AS (SELECT * FROM routen r WHERE EXISTS (SELECT 1 FROM pfad p WHERE p.rid = r.rid))
SELECT r.y AS abschnitt, r.rid, 'ein'::text AS rolle FROM r WHERE r.y IS NOT NULL
UNION ALL SELECT r.x, r.rid, 'aus' FROM r WHERE r.y IS NOT NULL
UNION ALL SELECT r.x, r.rid, 'ein' FROM r WHERE r.y IS NULL AND NOT EXISTS (SELECT 1 FROM r r2 WHERE r2.y = r.x)
UNION ALL SELECT r.x, r.rid, 'aus' FROM r WHERE r.y IS NULL AND NOT EXISTS (SELECT 1 FROM r r2 WHERE r2.x = r.x AND r2.y IS NOT NULL);
DELETE FROM rolle o WHERE NOT EXISTS (SELECT 1 FROM abschnitte a WHERE a.abschnitt = o.abschnitt AND a.im_gebiet);
CREATE INDEX ON rolle (abschnitt);
-- Routen, die Gabelungen und Naht bestimmen (stimme). gabel_durchgehend: aus = alle Routen; luecke = ohne Routen mit Brücke
-- oder Neuansatz (virtuelle Verbindung zwischen Teilrouten, Kennung -10000000 bis -999999999); teilrouten = ohne alle
-- Routen aus Teilrouten. Eine lückenhafte Route träfe die anderen erst dort, wo sie nach der Lücke wieder ansetzt, und
-- zöge die Gabelung weit vom RVN-Knoten weg (sonderfaelle/README.md, Mechanismus 3). Sie wird trotzdem an der Gabelung
-- geschnitten, wenn sie deren Knoten enthält (grenze), sonst an der Durchfahrt, und an der Naht bzw. ihrem Knoten
-- nächst der Naht (naht_folge). Ein Abschnitt ohne stimmende Route: alle Routen stimmen.
-- Berlin (RVN wie v7 je Kantenrichtung / Rückfälle): aus 9894 / 148; teilrouten ohne Kette 9884 / 131; mit Kette
-- (abschnitte_2_kette.sql, 300 m) aus 9897 / 145, luecke 9893 / 128, teilrouten 9901 / 124 (43 besser, 36 schlechter).
-- Mit der Kaskade (ZWEITLAUF=1, Teil 2): allein 9907 / 84; mit teilrouten 9891 / 70; mit Kette 9907 / 86; mit Kette
-- und teilrouten 9915 / 64 (49 besser, 28 schlechter, Rückfälle anders als v7 27 statt 58, 9812 je element_nr).
CREATE TEMP TABLE luecke AS
SELECT rid FROM bruecke WHERE :'gabel_durchgehend' = 'luecke'
UNION SELECT rid FROM pfad WHERE :'gabel_durchgehend' = 'luecke' AND edge <= -10000000 AND edge > -1000000000
UNION SELECT rid FROM teilroute WHERE :'gabel_durchgehend' = 'teilrouten';
CREATE INDEX ON luecke (rid);
CREATE TEMP TABLE stimme AS
SELECT DISTINCT o.abschnitt, o.rid FROM rolle o LEFT JOIN luecke l ON l.rid = o.rid WHERE l.rid IS NULL;
INSERT INTO stimme SELECT DISTINCT o.abschnitt, o.rid FROM rolle o
WHERE o.abschnitt NOT IN (SELECT abschnitt FROM stimme);
CREATE INDEX ON stimme (abschnitt, rid);
ANALYZE stimme;

-- Knoten je Route und Rolle mit Reihenfolge in der Route
CREATE TEMP TABLE rk AS
SELECT o.abschnitt, o.rolle, o.rid, p.node, min(p.seq) AS seq
FROM rolle o JOIN pfad p ON p.rid = o.rid AND p.node >= 0
GROUP BY 1, 2, 3, 4;
CREATE INDEX ON rk (abschnitt, rolle, rid, node);
ANALYZE rk;
-- Anzahl Routen je Abschnitt und Rolle, je eine Referenzroute für die Reihenfolge; Kreuzung bekannt: die Routen der
-- Rolle fahren durch eine Kreuzung (nicht nur Routen allein über s)
CREATE TEMP TABLE anzahl AS
SELECT o.abschnitt, count(DISTINCT o.rid) FILTER (WHERE o.rolle = 'ein') AS n_ein, count(DISTINCT o.rid) FILTER (WHERE o.rolle = 'aus') AS n_aus,
       count(DISTINCT o.rid) AS n_routen, min(o.rid) FILTER (WHERE o.rolle = 'ein') AS ref_ein, min(o.rid) FILTER (WHERE o.rolle = 'aus') AS ref_aus,
       coalesce(bool_or(r.y IS NOT NULL) FILTER (WHERE o.rolle = 'ein'), false) AS ein_kreuzung,
       coalesce(bool_or(r.y IS NOT NULL) FILTER (WHERE o.rolle = 'aus'), false) AS aus_kreuzung
FROM rolle o JOIN stimme st ON st.abschnitt = o.abschnitt AND st.rid = o.rid JOIN routen r ON r.rid = o.rid GROUP BY 1;
CREATE INDEX ON anzahl (abschnitt);
-- Routen je Knoten: in wie vielen ankommenden, abgehenden und allen Routen des Abschnitts der Knoten liegt
CREATE TEMP TABLE je_knoten AS
SELECT abschnitt, node, count(DISTINCT rid) FILTER (WHERE rolle = 'ein') AS in_ein, count(DISTINCT rid) FILTER (WHERE rolle = 'aus') AS in_aus,
       count(DISTINCT rid) AS in_alle, min(seq) FILTER (WHERE rolle = 'aus') AS seq_aus, max(seq) FILTER (WHERE rolle = 'ein') AS seq_ein
FROM rk WHERE (abschnitt, rid) IN (SELECT abschnitt, rid FROM stimme) GROUP BY 1, 2;
CREATE INDEX ON je_knoten (abschnitt, node);
ANALYZE anzahl, je_knoten;
-- Gabelungen je Abschnitt über gemeinsame Kanten (nicht nur gemeinsame Knoten: Routen, die sich an einem Knoten nur
-- berühren oder um eine Insel getrennt fahren und wieder zusammenkommen, sind dort nicht vereint):
--   vereinigung  erster Knoten in allen ankommenden Routen, ab dem alle dieselbe Kante weiterfahren (mindestens zwei)
--   teilung      letzter Knoten in allen abgehenden Routen, den alle über dieselbe Kante erreichen (mindestens zwei)
-- Reihenfolge entlang einer Referenzroute je Rolle.
CREATE TEMP TABLE kante_anz AS
SELECT o.abschnitt, o.rolle, p.edge, count(DISTINCT o.rid) AS n
FROM rolle o JOIN stimme st ON st.abschnitt = o.abschnitt AND st.rid = o.rid JOIN pfad p ON p.rid = o.rid AND p.edge >= 0 GROUP BY 1, 2, 3;
CREATE INDEX ON kante_anz (abschnitt, rolle, edge);
ANALYZE kante_anz;
CREATE TEMP TABLE ref AS
SELECT o.abschnitt, o.rolle, p.seq, p.node,
       CASE WHEN o.rolle = 'ein' THEN j.in_ein = n.n_ein ELSE j.in_aus = n.n_aus END AS knoten_in_allen,
       coalesce(ka.n, 0) = CASE WHEN o.rolle = 'ein' THEN n.n_ein ELSE n.n_aus END AS kante_weiter_in_allen
FROM rolle o
JOIN anzahl n ON n.abschnitt = o.abschnitt AND o.rid = CASE WHEN o.rolle = 'ein' THEN n.ref_ein ELSE n.ref_aus END
JOIN pfad p ON p.rid = o.rid AND p.node >= 0
JOIN je_knoten j ON j.abschnitt = o.abschnitt AND j.node = p.node
LEFT JOIN kante_anz ka ON ka.abschnitt = o.abschnitt AND ka.rolle = o.rolle AND ka.edge = p.edge
WHERE CASE WHEN o.rolle = 'ein' THEN n.n_ein ELSE n.n_aus END >= 2;
CREATE TEMP TABLE ref2 AS
SELECT r.*, coalesce(lag(r.kante_weiter_in_allen) OVER (PARTITION BY r.abschnitt, r.rolle ORDER BY r.seq), false) AS kante_davor_in_allen
FROM ref r;
CREATE TABLE gabelung AS
(SELECT DISTINCT ON (r.abschnitt) r.abschnitt, 'vereinigung'::text AS art, r.node, n.n_ein AS n_routen, k.geom
 FROM ref2 r JOIN anzahl n ON n.abschnitt = r.abschnitt JOIN routing_graph.knoten k ON k.id = r.node
 WHERE r.rolle = 'ein' AND r.knoten_in_allen AND r.kante_weiter_in_allen ORDER BY r.abschnitt, r.seq)
UNION ALL
(SELECT DISTINCT ON (r.abschnitt) r.abschnitt, 'teilung', r.node, n.n_aus, k.geom
 FROM ref2 r JOIN anzahl n ON n.abschnitt = r.abschnitt JOIN routing_graph.knoten k ON k.id = r.node
 WHERE r.rolle = 'aus' AND r.knoten_in_allen AND r.kante_davor_in_allen ORDER BY r.abschnitt, r.seq DESC);
CREATE INDEX ON gabelung (abschnitt, art);

-- Kandidaten für die Naht, Rang 1 bis 3:
--   1 vereinigung  die Vereinigung, wenn alle abgehenden Routen sie enthalten
--   2 teilung      die Teilung, wenn alle ankommenden Routen sie enthalten
--   3 gemeinsam    erster Knoten entlang s in allen Routen (fehlt ein solcher: in den meisten); gemeinsam_ende: der letzte,
--                  wenn nur die ankommende Seite eine Kreuzung kennt
CREATE TEMP TABLE kand AS
SELECT g.abschnitt, g.node, g.art, CASE WHEN g.art = 'vereinigung' THEN 1 ELSE 2 END AS rang, 0::float8 AS ordnung
FROM gabelung g JOIN anzahl n ON n.abschnitt = g.abschnitt JOIN je_knoten j ON j.abschnitt = g.abschnitt AND j.node = g.node
WHERE CASE WHEN g.art = 'vereinigung' THEN j.in_aus = n.n_aus ELSE j.in_ein = n.n_ein END
UNION ALL
SELECT j.abschnitt, j.node, CASE WHEN n.ein_kreuzung AND NOT n.aus_kreuzung THEN 'gemeinsam_ende' ELSE 'gemeinsam' END, 3,
       1e9 * (n.n_routen - j.in_alle) + CASE WHEN n.ein_kreuzung AND NOT n.aus_kreuzung
                                             THEN (1 - ST_LineLocatePoint(a.geom, k.geom)) * 1e6 - coalesce(j.seq_ein, 0)
                                             ELSE ST_LineLocatePoint(a.geom, k.geom) * 1e6 + coalesce(j.seq_aus, 1e5) END
FROM je_knoten j JOIN anzahl n ON n.abschnitt = j.abschnitt
JOIN abschnitte a ON a.abschnitt = j.abschnitt JOIN routing_graph.knoten k ON k.id = j.node;
CREATE TABLE naht AS
SELECT DISTINCT ON (c.abschnitt) c.abschnitt, c.art, c.node, j.in_alle AS n_mit, n.n_routen, n.n_ein, n.n_aus,
       ST_LineLocatePoint(a.geom, k.geom) * a.len AS lage_m, k.geom
FROM kand c JOIN je_knoten j ON j.abschnitt = c.abschnitt AND j.node = c.node JOIN anzahl n ON n.abschnitt = c.abschnitt
JOIN abschnitte a ON a.abschnitt = c.abschnitt JOIN routing_graph.knoten k ON k.id = c.node
ORDER BY c.abschnitt, c.rang, c.ordnung;
ALTER TABLE naht ADD PRIMARY KEY (abschnitt);

-- Durchfahrt je Route und Rolle: Folge des Knotens, der dem Anfang (ein) bzw. Ende (aus) von s am nächsten liegt
CREATE TABLE durchfahrt AS
SELECT DISTINCT ON (o.abschnitt, o.rid, o.rolle) o.abschnitt, o.rid, o.rolle, p.seq
FROM rolle o JOIN abschnitte a ON a.abschnitt = o.abschnitt
JOIN pfad p ON p.rid = o.rid AND p.node >= 0 JOIN routing_graph.knoten k ON k.id = p.node
ORDER BY o.abschnitt, o.rid, o.rolle, ST_Distance(k.geom, CASE WHEN o.rolle = 'ein' THEN ST_StartPoint(a.geom) ELSE ST_EndPoint(a.geom) END), p.seq;
CREATE INDEX ON durchfahrt (abschnitt, rid, rolle);
-- Grenze je Route und Rolle zwischen Kreuzung und Abschnitt: für eine ankommende Route die Vereinigung, für eine
-- abgehende die Teilung; gibt es die Gabelung nicht (nur eine Route), die Durchfahrt
CREATE TABLE grenze AS
SELECT d.abschnitt, d.rid, d.rolle, coalesce(r.seq, d.seq) AS seq, (r.seq IS NOT NULL) AS an_gabelung
FROM durchfahrt d
LEFT JOIN gabelung g ON g.abschnitt = d.abschnitt AND g.art = CASE WHEN d.rolle = 'ein' THEN 'vereinigung' ELSE 'teilung' END
LEFT JOIN rk r ON r.abschnitt = d.abschnitt AND r.rolle = d.rolle AND r.rid = d.rid AND r.node = g.node;
CREATE INDEX ON grenze (abschnitt, rid, rolle);
ANALYZE grenze;
-- Folge der Naht je Route und Rolle: an ihrem Knoten; mit gabel_durchgehend bekommt eine Route ohne den Knoten der Naht
-- (sonst fällt sie weg) ihren Knoten nächst der Naht auf der richtigen Seite der Grenze
CREATE TEMP TABLE naht_folge AS
SELECT o.abschnitt, o.rid, o.rolle, t.seq
FROM rolle o JOIN naht n ON n.abschnitt = o.abschnitt JOIN pfad t ON t.rid = o.rid AND t.node = n.node;
INSERT INTO naht_folge
SELECT DISTINCT ON (o.abschnitt, o.rid, o.rolle) o.abschnitt, o.rid, o.rolle, p.seq
FROM rolle o JOIN naht n ON n.abschnitt = o.abschnitt
JOIN grenze d ON d.abschnitt = o.abschnitt AND d.rid = o.rid AND d.rolle = o.rolle
JOIN pfad p ON p.rid = o.rid AND p.node >= 0 AND CASE WHEN o.rolle = 'ein' THEN p.seq > d.seq ELSE p.seq < d.seq END
JOIN routing_graph.knoten k ON k.id = p.node
WHERE :'gabel_durchgehend' <> 'aus'
  AND NOT EXISTS (SELECT 1 FROM naht_folge f WHERE f.abschnitt = o.abschnitt AND f.rid = o.rid AND f.rolle = o.rolle)
ORDER BY o.abschnitt, o.rid, o.rolle, ST_Distance(k.geom, n.geom), p.seq;
CREATE INDEX ON naht_folge (abschnitt, rid, rolle);

-- Abschnittsmitten: ankommend von der Grenze (Vereinigung bzw. Durchfahrt durch b) bis zur Naht, abgehend von der Naht
-- bis zur Grenze (Teilung bzw. Durchfahrt durch c), lückenlos
CREATE TABLE abschnitt_pfad AS
SELECT o.abschnitt, o.rid, o.rolle, p.seq, g.id AS kante, CASE WHEN p.node = g.source THEN 0 ELSE 1 END AS ri,
       CASE WHEN p.node = g.source THEN g.objekt0 ELSE g.objekt1 END AS objekt,
       coalesce(CASE WHEN p.node = g.source THEN g.fuehr0 ELSE g.fuehr1 END, 'Keine Radinfrastruktur vorhanden') AS fuehr,
       CASE WHEN p.node = g.source THEN g.faktor0 ELSE g.faktor1 END AS faktor,
       CASE WHEN p.node = g.source THEN g.geom ELSE ST_Reverse(g.geom) END AS geom
FROM rolle o
JOIN naht_folge t ON t.abschnitt = o.abschnitt AND t.rid = o.rid AND t.rolle = o.rolle
JOIN grenze d ON d.abschnitt = o.abschnitt AND d.rid = o.rid AND d.rolle = o.rolle
JOIN pfad p ON p.rid = o.rid AND p.edge >= 0
     AND CASE WHEN o.rolle = 'ein' THEN p.seq >= d.seq AND p.seq < t.seq ELSE p.seq >= t.seq AND p.seq < d.seq END
JOIN routing_graph.g g ON g.id = p.edge;
CREATE INDEX ON abschnitt_pfad (abschnitt);

CREATE TABLE abschnitt_route AS
SELECT abschnitt, rid, rolle, count(*) AS kanten, round(sum(ST_Length(geom))::numeric, 1) AS m,
       ST_Multi(ST_LineMerge(ST_Collect(geom ORDER BY seq)))::geometry(MultiLineString, 25833) AS geom
FROM abschnitt_pfad GROUP BY 1, 2, 3;

-- Kreuzungsstücke: je Route x -> y die Fahrt durch die RVN-Kreuzung (Knoten zwischen x und y), von ihrer Grenze auf x
-- (Teilung von x bzw. Durchfahrt) bis zu ihrer Grenze auf y (Vereinigung von y bzw. Durchfahrt)
CREATE TABLE kreuzung_pfad AS
SELECT r.rid, r.x, r.y, ax.nach AS knoten, p.seq, g.id AS kante, CASE WHEN p.node = g.source THEN 0 ELSE 1 END AS ri,
       CASE WHEN p.node = g.source THEN g.objekt0 ELSE g.objekt1 END AS objekt,
       coalesce(CASE WHEN p.node = g.source THEN g.fuehr0 ELSE g.fuehr1 END, 'Keine Radinfrastruktur vorhanden') AS fuehr,
       CASE WHEN p.node = g.source THEN g.faktor0 ELSE g.faktor1 END AS faktor,
       CASE WHEN p.node = g.source THEN g.geom ELSE ST_Reverse(g.geom) END AS geom
FROM routen r JOIN abschnitte ax ON ax.abschnitt = r.x
JOIN grenze gx ON gx.abschnitt = r.x AND gx.rid = r.rid AND gx.rolle = 'aus'
JOIN grenze gy ON gy.abschnitt = r.y AND gy.rid = r.rid AND gy.rolle = 'ein'
JOIN pfad p ON p.rid = r.rid AND p.edge >= 0 AND p.seq >= gx.seq AND p.seq < gy.seq
JOIN routing_graph.g g ON g.id = p.edge
WHERE r.y IS NOT NULL;
CREATE INDEX ON kreuzung_pfad (x); CREATE INDEX ON kreuzung_pfad (y);

-- Haupt-Führungsform je Kreuzungsfahrt: längste Summe
CREATE TEMP TABLE kreuzung_haupt AS
SELECT DISTINCT ON (rid) rid, fuehr FROM (SELECT rid, fuehr, sum(ST_Length(geom)) AS m FROM kreuzung_pfad GROUP BY 1, 2) x
ORDER BY rid, m DESC;
CREATE INDEX ON kreuzung_haupt (rid);
CREATE TABLE kreuzung_route AS
SELECT k.rid, k.x, k.y, k.knoten, count(*) AS kanten, round(sum(ST_Length(k.geom))::numeric, 1) AS m, h.fuehr,
       string_agg(DISTINCT k.fuehr, ', ') AS fuehr_alle,
       -- unbequem: Kreuzungsstück über Zusatzkanten des zweiten Laufs (Treppe, Erschließungsstraße, Baustelle)
       string_agg(DISTINCT gz.zusatz, ', ') AS zusatz, round((sum(ST_Length(k.geom)) FILTER (WHERE gz.zusatz IS NOT NULL))::numeric, 1) AS zusatz_m,
       bool_or(gz.zusatz IS NOT NULL) AS unbequem,
       bool_and(gx.an_gabelung) AS von_gabelung, bool_and(gy.an_gabelung) AS bis_gabelung,
       ST_Multi(ST_LineMerge(ST_Collect(k.geom ORDER BY k.seq)))::geometry(MultiLineString, 25833) AS geom
FROM kreuzung_pfad k JOIN routing_graph.g gz ON gz.id = k.kante
JOIN grenze gx ON gx.abschnitt = k.x AND gx.rid = k.rid AND gx.rolle = 'aus'
JOIN grenze gy ON gy.abschnitt = k.y AND gy.rid = k.rid AND gy.rolle = 'ein'
JOIN kreuzung_haupt h ON h.rid = k.rid
GROUP BY k.rid, k.x, k.y, k.knoten, h.fuehr;

-- 4. Projektion auf die RVN-Kanten des Abschnitts (Lage im Abschnitt -> Digitalisierungsmeter der RVN-Kante): die
-- Abschnittsmitten; ein Abschnitt ohne Mitte (Gabelungen überlappen) bekommt die Kreuzungsstücke der Routen über ihn.
-- kreuzung_alle: keine Trennung von Mitte und Kreuzung, die Kreuzungsstücke zählen auf beiden Abschnitten (x und y) immer
-- mit; Stücke jenseits des Abschnittsendes fallen bei der Projektion weg.
-- ganze_routen (Standard false): ohne Mitten und Naht, jede Route ganz: jede Kante ihres Wegs zählt auf dem näheren ihrer
-- beiden Abschnitte (Abstand der Kantenmitte zur Abschnittslinie; eine Route allein über x ganz auf x). Keine Route fällt
-- weg, keine Lücke zwischen Mitte und Kreuzung; Nähte, Gabelungen und Kreuzungsstücke bleiben nur zur Darstellung.
CREATE TEMP TABLE mit_mitte AS SELECT DISTINCT abschnitt FROM abschnitt_pfad;
CREATE INDEX ON mit_mitte (abschnitt);
CREATE TABLE rvn_stuecke AS
WITH stueck AS (
    SELECT abschnitt, rid, rolle, seq, kante, objekt, fuehr, faktor, geom FROM abschnitt_pfad WHERE NOT :ganze_routen
    UNION ALL
    SELECT s.abschnitt, k.rid, 'kreuzung', k.seq, k.kante, k.objekt, k.fuehr, k.faktor, k.geom
    FROM kreuzung_pfad k JOIN abschnitte s ON s.abschnitt IN (k.x, k.y) AND s.im_gebiet
    LEFT JOIN mit_mitte m ON m.abschnitt = s.abschnitt WHERE NOT :ganze_routen AND (m.abschnitt IS NULL OR :kreuzung_alle)
    UNION ALL
    SELECT CASE WHEN ay.abschnitt IS NULL OR ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), ax.geom)
                                             <= ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), ay.geom) THEN r.x ELSE r.y END,
           r.rid, CASE WHEN ay.abschnitt IS NULL OR ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), ax.geom)
                                                   <= ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), ay.geom) THEN 'aus' ELSE 'ein' END,
           p.seq, g.id, CASE WHEN p.node = g.source THEN g.objekt0 ELSE g.objekt1 END,
           coalesce(CASE WHEN p.node = g.source THEN g.fuehr0 ELSE g.fuehr1 END, 'Keine Radinfrastruktur vorhanden'),
           CASE WHEN p.node = g.source THEN g.faktor0 ELSE g.faktor1 END,
           CASE WHEN p.node = g.source THEN g.geom ELSE ST_Reverse(g.geom) END
    FROM routen r JOIN pfad p ON p.rid = r.rid AND p.edge >= 0 JOIN routing_graph.g g ON g.id = p.edge
    JOIN abschnitte ax ON ax.abschnitt = r.x LEFT JOIN abschnitte ay ON ay.abschnitt = r.y
    WHERE :ganze_routen
), lage AS (
    SELECT ap.*, least(q.a, q.b) AS x1, greatest(q.a, q.b) AS x2
    FROM stueck ap JOIN abschnitte a ON a.abschnitt = ap.abschnitt,
    LATERAL (SELECT ST_LineLocatePoint(a.geom, ST_StartPoint(ap.geom)) * a.len AS a, ST_LineLocatePoint(a.geom, ST_EndPoint(ap.geom)) * a.len AS b) q
), teil AS (
    SELECT l.abschnitt, l.rid, l.rolle, l.seq, l.kante, l.objekt, l.fuehr, l.faktor, k.rvn_id, k.element_nr, k.ri, k.len,
           greatest(l.x1, k.lage_m) - k.lage_m AS d1, least(l.x2, k.lage_m + k.len) - k.lage_m AS d2
    FROM lage l, abschnitt_kanten k
    WHERE k.abschnitt = l.abschnitt AND k.lage_m < l.x2 AND k.lage_m + k.len > l.x1
)
SELECT abschnitt, rid, rolle, seq, kante, objekt, fuehr, faktor, rvn_id, element_nr, ri,
       CASE WHEN ri = 0 THEN d1 ELSE len - d2 END AS von, CASE WHEN ri = 0 THEN d2 ELSE len - d1 END AS bis
FROM teil WHERE d2 - d1 > 0.01;
CREATE INDEX ON rvn_stuecke (rvn_id, ri);

-- Führungsform je RVN-Kante und Richtung (:abstimmung):
--   summe   längste Summe der Stücke aller Routen je Form
--   stelle  wie v7 erst je Stelle, dann je Kante: Elementarintervalle aus allen Stückgrenzen, je Intervall die Form der
--           besten Stufe unter den dort liegenden Stücken (Radinfrastruktur vor Mischverkehr vor Sonstigen Wegen vor keiner;
--           gleiche Stufe: mehr Routen), dann je Kante die Form mit der größten Länge. Nebeneinander liegende Formen (Fahrbahn
--           und Seitenweg an derselben Stelle) entscheidet die Stufe, nacheinander liegende die Länge.
-- Abdeckung = Anteil der Kante unter mindestens einem Stück.
-- Kreuzungsweg stimmt nur mit, wenn die übrigen Formen höchstens kreuzung_anteil der Kante überdecken (Vereinigung ihrer
-- Stücke): sonst gewinnen die Querungen der Seitenstraßen entlang der Kante, die sich über mehrere Routen aufsummieren.
-- Rückfall wie im HMM (v7: kein gewinnender TILDA-Weg -> no_infra_fuehr): eine Kantenrichtung ohne Stück bekommt
-- "Keine Radinfrastruktur vorhanden" (rueckfall = true). zusatz: Stücke auf Zusatzkanten des zweiten Laufs (treppe, service;
-- abschnitte_2c_zweitlauf.sql) mit ihren Metern.
SELECT :'abstimmung' = 'stelle' AS abst_stelle \gset
\if :abst_stelle
CREATE FUNCTION pg_temp.stufe(f text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN f IN ('Radfahrstreifen', 'Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)',
                         'Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)', 'Geschützter Radfahrstreifen', 'Schutzstreifen',
                         'Fahrradstraße /-zone (Z 244)', 'Radweg', 'Gemeinsamer Geh- und Radweg mit Z240',
                         'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)', 'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)',
                         'Kreuzungsweg', '[TODO] Klärung notwendig') THEN 1
              WHEN f = 'Mischverkehr mit motorisiertem Verkehr' THEN 2
              WHEN f IS NULL OR f = 'Keine Radinfrastruktur vorhanden' THEN 4 ELSE 3 END $$;
CREATE TEMP TABLE st_grenzen AS
SELECT DISTINCT rvn_id, ri, x FROM (SELECT rvn_id, ri, von AS x FROM rvn_stuecke UNION ALL SELECT rvn_id, ri, bis FROM rvn_stuecke) y;
CREATE TEMP TABLE st_iv AS SELECT rvn_id, ri, x AS a, lead(x) OVER (PARTITION BY rvn_id, ri ORDER BY x) AS b FROM st_grenzen;
DELETE FROM st_iv WHERE b IS NULL OR b - a < 0.01;
CREATE INDEX ON st_iv (rvn_id, ri);
CREATE TEMP TABLE st_form AS
SELECT i.rvn_id, i.ri, i.a, i.b, s.fuehr, count(DISTINCT s.rid) AS routen
FROM st_iv i JOIN rvn_stuecke s ON s.rvn_id = i.rvn_id AND s.ri = i.ri AND s.von <= i.a + 0.001 AND s.bis >= i.b - 0.001
GROUP BY 1, 2, 3, 4, 5;
CREATE TEMP TABLE je_basis AS
SELECT rvn_id, ri, fuehr, sum(b - a) AS m FROM (
    SELECT DISTINCT ON (rvn_id, ri, a) rvn_id, ri, a, b, fuehr FROM st_form ORDER BY rvn_id, ri, a, pg_temp.stufe(fuehr), routen DESC) x
GROUP BY 1, 2, 3;
\else
CREATE TEMP TABLE je_basis AS SELECT rvn_id, ri, fuehr, sum(bis - von) AS m FROM rvn_stuecke GROUP BY 1, 2, 3;
\endif
CREATE INDEX ON je_basis (rvn_id, ri);
CREATE TABLE ergebnis AS
WITH je_alle AS (
    SELECT rvn_id, ri, fuehr, m FROM je_basis
), andere AS (
    SELECT s.rvn_id, s.ri, sum(upper(x) - lower(x)) AS m
    FROM (SELECT rvn_id, ri, range_agg(numrange(von::numeric, bis::numeric)) AS r FROM rvn_stuecke WHERE fuehr <> 'Kreuzungsweg' GROUP BY 1, 2) s,
         unnest(s.r) x
    GROUP BY 1, 2
), je_fuehr AS (
    SELECT j.rvn_id, j.ri, j.fuehr, j.m FROM je_alle j
    LEFT JOIN andere o ON o.rvn_id = j.rvn_id AND o.ri = j.ri
    LEFT JOIN (SELECT rvn_id, max(len) AS len FROM abschnitt_kanten GROUP BY 1) l ON l.rvn_id = j.rvn_id
    WHERE NOT (j.fuehr = 'Kreuzungsweg' AND coalesce(o.m, 0) > :kreuzung_anteil * l.len)
), zusatz AS (
    SELECT s.rvn_id, s.ri, string_agg(DISTINCT g.zusatz, ', ') AS arten, sum(s.bis - s.von) AS m
    FROM rvn_stuecke s JOIN routing_graph.g g ON g.id = s.kante WHERE g.zusatz IS NOT NULL GROUP BY 1, 2
), abdeckung AS (
    SELECT s.rvn_id, s.ri, sum(upper(x) - lower(x)) AS m
    FROM (SELECT rvn_id, ri, range_agg(numrange(von::numeric, bis::numeric)) AS r FROM rvn_stuecke GROUP BY 1, 2) s, unnest(s.r) x
    GROUP BY 1, 2
)
SELECT DISTINCT ON (k.rvn_id, k.ri) k.rvn_id, k.element_nr, k.ri, k.abschnitt,
       coalesce(j.fuehr, 'Keine Radinfrastruktur vorhanden') AS fuehr, j.fuehr IS NULL AS rueckfall, round(j.m::numeric, 1) AS m,
       round((sum(j.m) OVER (PARTITION BY k.rvn_id, k.ri))::numeric, 1) AS m_gesamt,
       round((d.m / k.len::numeric), 2) AS abdeckung, z.arten AS zusatz, round(z.m::numeric, 1) AS zusatz_m, z.arten IS NOT NULL AS unbequem,
       -- Führungsform aus den Stücken des besten Wegs; Teil 4 kann fuehr durch einen Kandidaten ersetzen
       coalesce(j.fuehr, 'Keine Radinfrastruktur vorhanden') AS fuehr_weg, false AS kandidat, NULL::numeric AS kandidat_mehr
FROM abschnitt_kanten k JOIN abschnitte a ON a.abschnitt = k.abschnitt AND a.im_gebiet
LEFT JOIN je_fuehr j ON j.rvn_id = k.rvn_id AND j.ri = k.ri
LEFT JOIN abdeckung d ON d.rvn_id = k.rvn_id AND d.ri = k.ri
LEFT JOIN zusatz z ON z.rvn_id = k.rvn_id AND z.ri = k.ri
ORDER BY k.rvn_id, k.ri, j.m DESC NULLS LAST;

\echo 'Abschnitte im Gebiet, Routen, Routen aus Teilrouten, Brücken, Routen ohne Weg'
SELECT (SELECT count(*) FROM abschnitte WHERE im_gebiet) AS abschnitte,
       (SELECT count(*) FROM routen) AS routen,
       (SELECT count(DISTINCT rid) FROM teilroute) AS aus_teilrouten, (SELECT count(*) FROM bruecke) AS bruecken,
       (SELECT count(*) FROM routen r WHERE NOT EXISTS (SELECT 1 FROM pfad p WHERE p.rid = r.rid)) AS ohne_weg;
\echo 'Nähte: Art, Routen mit Naht / alle Routen'
SELECT art, n_mit = n_routen AS in_allen, count(*) AS abschnitte FROM naht GROUP BY 1, 2 ORDER BY 1, 2;
