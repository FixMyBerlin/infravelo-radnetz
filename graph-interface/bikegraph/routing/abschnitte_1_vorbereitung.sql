-- Routing der RVN-Abschnitte, Teil 1 Vorbereitung (abschnitte.sh): das RVN als gewichtete kürzeste Wege durch den
-- Routing-Graphen (graph.sql). Teil 2 (abschnitte_2_routing.sql) sucht die Wege parallel, Teil 3
-- (abschnitte_3_auswertung.sql) setzt sie zusammen.
-- 1. Abschnitte: gerichtete RVN-Kanten (Fahrtrichtungen laut RVN: B beide, R und G nur Digitalisierungsrichtung), über
--    Knoten mit Grad 2 (genau zwei RVN-Kanten) zu Abschnitten zwischen Kreuzungen und Netzenden verkettet. Ein Abschnitt
--    endet auch dort, wo die nächste Kante in seiner Richtung fehlt (Einrichtungskante). Getrennte Fahrbahnen (Kette
--    aus Einbahnkanten mit einer Gegenkette zwischen denselben Knoten) zählen an ihren Enden als eine RVN-Kante: wo sich
--    nur die Fahrbahnen teilen oder vereinigen und die Straße weitergeht, ist keine Kreuzung (Tabelle einbahn_kette).
-- 2. Routen: je Knoten jeder ankommende Abschnitt x mit jedem abgehenden y (ohne Wende auf dieselbe RVN-Kante oder auf
--    die Gegenfahrbahn), kürzester
--    Weg von der Startmenge am Anfang von x zur Zielmenge am Ende von y, nur über Kanten, die ganz im Korridor liegen
--    (Puffer :korridor_m um x und y): eine lange Kante, die den Korridor nur berührt, wäre sonst eine Abkürzung, z. B.
--    direkt von a nach c statt über b oder über einen anderen RVN-Weg c -> e -> a.
--    Ein Abschnitt ohne ankommende oder ohne abgehende Route (Netzende) bekommt dafür eine Route nur über sich selbst.
-- 3. Naht je Abschnitt s: die ankommenden Routen (y = s) kennen die Einfahrt in s, die abgehenden (x = s) die Ausfahrt.
--    Naht an einer Gabelung, nur aus Routen durch dieselbe Kreuzung bestimmt (Start und Ziel einer Route liegen dann
--    außerhalb): Vereinigung = wo alle ankommenden Routen zusammenkommen und dieselbe Kante weiterfahren (mindestens
--    zwei, alle abgehenden enthalten den Knoten); sonst Teilung = wo die abgehenden Routen auseinandergehen, zuletzt
--    über dieselbe Kante angekommen (mindestens zwei, alle ankommenden enthalten den Knoten); sonst erster Knoten entlang s, der in allen Routen liegt (fehlt ein solcher: der in den meisten) -
--    der letzte, wenn nur die ankommende Seite eine Kreuzung kennt (abgehend keine Route oder nur eine Route allein über
--    s bis zum Netzende): dann bestimmt die ankommende Route den ganzen Abschnitt.
--    Reihenfolge entlang der Routen (Folge im Pfad). Von den ankommenden Routen bleibt das Stück bis zur Naht, von den
--    abgehenden das Stück ab der Naht; Routen ohne die Naht fallen weg.
--    Kreuzungen: beide Gabelungen je Abschnitt bleiben (Tabelle gabelung), die Vereinigung am Anfang und die Teilung am
--    Ende. Die Stücke einer Route zwischen der Teilung ihres ankommenden und der Vereinigung ihres abgehenden Abschnitts
--    sind ihre Fahrt durch die RVN-Kreuzung (Tabelle kreuzung_pfad); zum Abschnitt gehört nur die Mitte dazwischen.
--    Fehlt eine Gabelung (nur eine Route auf dieser Seite), ist die Grenze die Durchfahrt (unten).
--    Durchfahrt: eine ankommende Route gehört erst ab dem Knoten zu s, an dem sie dem
--    Anfangsknoten von s (RVN-Kreuzung b) am nächsten kommt, eine abgehende nur bis zu dem Knoten, an dem sie dem
--    Endknoten (c) am nächsten kommt; davor bzw. danach fährt sie auf dem vorigen bzw. nächsten Abschnitt, auch wenn der
--    neben s zurückläuft. Der Teil einer ankommenden Route vor s gehört dort zu ihr als abgehende Route, der Teil einer
--    abgehenden Route nach s zum nächsten Abschnitt. Die Stücke sind lückenlos; Kanten, die auf die Linie von s mit
--    Länge 0 fallen (an der Kreuzung), zählen erst bei der Projektion nicht.
-- 4. Die Abschnittsmitten auf die RVN-Kanten des Abschnitts projiziert; Führungsform je RVN-Kante und Richtung: längste
--    Summe (jede Route zählt, Überlappungen also mehrfach). Kreuzungsstücke zählen nur für Abschnitte ohne Mitte.
-- Start- und Zielmengen: Knoten im Umkreis :fang_m im Korridor, getrennt (ein Knoten gehört zum näheren der beiden Punkte).
-- Kosten der virtuellen Kanten = übersprungene RVN-Meter x anschluss_faktor + seitlicher Abstand x quer_faktor; Kosten
-- jeder Kante des Graphen = Länge x Faktor (graph.sql).
-- Eingang: routing_graph.g, routing_graph.knoten (graph.sql), matching.reference_edges (RVN)
-- Ausgang (Schema :schema, Standard routing_abschnitte):
--   abschnitte, abschnitt_kanten  gerichtete Abschnitte (Linie in Fahrtrichtung) und ihre RVN-Kanten (Lage im Abschnitt)
--   einbahn_kette                 Ketten aus Einbahn-RVN-Kanten, gegen = Kette der Gegenfahrbahn (getrennte Fahrbahnen)
--   routen, pfad                  Routen und ihre kürzesten Wege (pgr_dijkstra); Routen ohne Weg aus Teilrouten je
--                                 RVN-Kante zusammengesetzt (teilroute), Teilrouten ohne Weg mit Brücke
--   bruecke                       je Teilroute ohne Weg die Brücke über die Netzlücke (Knoten a, b, Länge, Linie)
--   naht                          Naht je Abschnitt: Art (vereinigung, teilung, gemeinsam), Knoten, Lage im Abschnitt,
--                                 Routen mit Naht / alle Routen
--   gabelung                      je Abschnitt Vereinigung (Anfang) und Teilung (Ende)
--   abschnitt_pfad                Abschnittsmitten: je Abschnitt die Kanten der ankommenden Routen von der Vereinigung
--                                 bis zur Naht und der abgehenden von der Naht bis zur Teilung, mit Objekt und Führungsform
--   abschnitt_route               dasselbe je Abschnitt und Route als eine Linie
--   kreuzung_pfad, kreuzung_route Fahrten durch die RVN-Kreuzungen: je Route x -> y die Kanten zwischen der Teilung von x
--                                 und der Vereinigung von y, mit RVN-Knoten; als Linie mit Haupt-Führungsform
--   rvn_stuecke                   die Kanten auf die RVN-Kanten projiziert (rvn_id = matching.reference_edges.id, Lage in
--                                 Digitalisierungsmetern)
--   ergebnis                      Führungsform je RVN-Kante und Richtung, Abdeckung
-- psql-Variablen: schema (Standard routing_abschnitte), lon, lat, radius_m (Abschnitte im Umkreis; 0 = ganzes RVN), korridor_m, fang_m, anschluss_faktor,
-- quer_faktor, schnitt_m (Umkreis um Kreuzung, Start und Ziel, in dem Kanten anderer RVN-Kanten und Wechsel von x
-- nach y erlaubt sind, Standard 50), brueck_m (Brücken über Netzlücken: größter Abstand, Standard 50), brueck_faktor (Kosten je m
-- Brücke, Standard 10), fortschritt (Fortschrittskosten, Standard false), fortschritt_toleranz_m (Standard 0),
-- abstand_faktor (Standard 0.1), abstand_sigma_m (Standard 10), name_faktor (Standard 0 = aus), naechste_toleranz_m
-- (Standard 10, 0 = aus); siehe korridor_kanten
\if :{?schema} \else \set schema routing_abschnitte \endif
\if :{?naechste_toleranz_m} \else \set naechste_toleranz_m 10 \endif
\if :{?lon} \else \set lon 13.35009 \endif
\if :{?lat} \else \set lat 52.51450 \endif
\if :{?radius_m} \else \set radius_m 150 \endif
\if :{?korridor_m} \else \set korridor_m 50 \endif
\if :{?fang_m} \else \set fang_m 50 \endif
\if :{?anschluss_faktor} \else \set anschluss_faktor 2.0 \endif
\if :{?quer_faktor} \else \set quer_faktor 0.2 \endif
\if :{?brueck_m} \else \set brueck_m 50 \endif
\if :{?schnitt_m} \else \set schnitt_m 50 \endif
\if :{?fortschritt} \else \set fortschritt false \endif
\if :{?fortschritt_toleranz_m} \else \set fortschritt_toleranz_m 0 \endif
\if :{?abstand_faktor} \else \set abstand_faktor 0.1 \endif
\if :{?abstand_sigma_m} \else \set abstand_sigma_m 10 \endif
\if :{?name_faktor} \else \set name_faktor 0 \endif
\if :{?brueck_faktor} \else \set brueck_faktor 10 \endif
DROP SCHEMA IF EXISTS :"schema" CASCADE;
CREATE SCHEMA :"schema";
SET search_path TO :"schema", public;

-- 1. Abschnitte
-- gerichtete RVN-Kanten (Geometrie in Fahrtrichtung). Schlüssel ist die id: manche element_nr gibt es mehrfach (Stücke)
CREATE TEMP TABLE rv AS
SELECT r.id AS rvn_id, r.element_nr, k.ri, CASE WHEN k.ri = 0 THEN r.source ELSE r.target END AS von, CASE WHEN k.ri = 0 THEN r.target ELSE r.source END AS nach,
       r.verkehrsrichtung, CASE WHEN k.ri = 0 THEN r.geom ELSE ST_Reverse(r.geom) END AS geom, ST_Length(r.geom) AS len
FROM matching.reference_edges r, (VALUES (0), (1)) k(ri)
WHERE ST_Length(r.geom) > 0 AND (k.ri = 0 OR coalesce(r.verkehrsrichtung, 'B') NOT IN ('R', 'G'));
CREATE INDEX ON rv (rvn_id, ri); CREATE INDEX ON rv (von); CREATE INDEX ON rv (nach);
-- Grad je RVN-Knoten (Anzahl verschiedener RVN-Kanten)
CREATE TEMP TABLE grad AS
SELECT k, count(DISTINCT id) AS grad FROM (
    SELECT source AS k, id FROM matching.reference_edges UNION ALL SELECT target, id FROM matching.reference_edges) x
GROUP BY 1;
CREATE INDEX ON grad (k);
-- Richtungsfahrbahnen: Ketten aus Einbahn-RVN-Kanten (R, G) über Knoten mit Grad 2; eine Kette a -> b, zu der es
-- zwischen denselben Knoten eine Kette b -> a gibt (Gegenfahrbahn), ist mit ihr eine getrennte Fahrbahn (z. B.
-- Karl-Marx-Allee am Strausberger Platz). Das Paar zählt an seinen Enden als eine RVN-Kante (grad), dort ist also keine
-- Kreuzung, wenn sonst nur die Fortsetzung anschließt; der Wechsel von einer Kette auf ihre Gegenfahrbahn am selben Knoten
-- ist eine Wende (Tabelle wende: ankommende letzte Kante a_id, abgehende erste Kante b_id), weder Fortsetzung eines
-- Abschnitts noch Route x -> y.
CREATE TEMP TABLE einbahn_weiter AS
SELECT a.rvn_id, b.rvn_id AS n_id
FROM rv a JOIN grad g ON g.k = a.nach AND g.grad = 2 JOIN rv b ON b.von = a.nach AND b.rvn_id <> a.rvn_id
WHERE coalesce(a.verkehrsrichtung, 'B') IN ('R', 'G') AND coalesce(b.verkehrsrichtung, 'B') IN ('R', 'G');
CREATE TABLE einbahn_kette AS
WITH RECURSIVE kette AS (
    SELECT rv.rvn_id AS kette, 1 AS pos, rv.rvn_id FROM rv
    WHERE coalesce(rv.verkehrsrichtung, 'B') IN ('R', 'G') AND NOT EXISTS (SELECT 1 FROM einbahn_weiter w WHERE w.n_id = rv.rvn_id)
    UNION ALL
    SELECT k.kette, k.pos + 1, w.n_id FROM kette k JOIN einbahn_weiter w ON w.rvn_id = k.rvn_id WHERE k.pos < 10000
)
SELECT k.kette, (array_agg(rv.von ORDER BY k.pos))[1] AS von, (array_agg(rv.nach ORDER BY k.pos DESC))[1] AS nach,
       (array_agg(k.rvn_id ORDER BY k.pos))[1] AS erst_kante, (array_agg(k.rvn_id ORDER BY k.pos DESC))[1] AS letzt_kante,
       count(*)::int AS kanten, sum(rv.len) AS len, ST_MakeLine(array_agg(rv.geom ORDER BY k.pos)) AS geom
FROM kette k JOIN rv ON rv.rvn_id = k.rvn_id GROUP BY k.kette;
ALTER TABLE einbahn_kette ADD COLUMN gegen int;
UPDATE einbahn_kette a SET gegen = b.kette
FROM einbahn_kette b WHERE b.von = a.nach AND b.nach = a.von AND a.von <> a.nach
  AND (SELECT count(*) FROM einbahn_kette c WHERE c.von = a.nach AND c.nach = a.von) = 1
  AND (SELECT count(*) FROM einbahn_kette c WHERE c.von = b.nach AND c.nach = b.von) = 1;
CREATE TEMP TABLE wende AS
SELECT a.nach AS k, a.letzt_kante AS a_id, b.erst_kante AS b_id
FROM einbahn_kette a JOIN einbahn_kette b ON b.kette = a.gegen;
CREATE INDEX ON wende (a_id, b_id);
UPDATE grad g SET grad = g.grad - w.n FROM (SELECT k, count(*) AS n FROM wende GROUP BY k) w WHERE w.k = g.k;
\echo 'Einbahn-Ketten, davon mit Gegenfahrbahn (getrennte Fahrbahnen), Knoten dadurch ohne Kreuzung (Grad 2)'
SELECT count(*) AS ketten, count(gegen) AS mit_gegenfahrbahn,
       (SELECT count(*) FROM grad g WHERE g.grad = 2 AND g.k IN (SELECT k FROM wende)) AS knoten_ohne_kreuzung
FROM einbahn_kette;
-- Nachfolger je gerichteter Kante über einen Grad-2-Knoten (ohne Wende auf die Gegenfahrbahn)
CREATE TEMP TABLE weiter AS
SELECT a.rvn_id, a.ri, b.rvn_id AS n_id, b.ri AS n_ri
FROM rv a JOIN grad g ON g.k = a.nach AND g.grad = 2 JOIN rv b ON b.von = a.nach AND b.rvn_id <> a.rvn_id
WHERE NOT EXISTS (SELECT 1 FROM wende w WHERE w.a_id = a.rvn_id AND w.b_id = b.rvn_id);
CREATE INDEX ON weiter (rvn_id, ri); CREATE INDEX ON weiter (n_id, n_ri);
-- Ketten ab jeder Kante ohne Vorgänger
CREATE TABLE abschnitt_kanten AS
WITH RECURSIVE kette AS (
    SELECT row_number() OVER (ORDER BY rv.element_nr, rv.rvn_id, rv.ri)::int AS abschnitt, 1 AS pos, rv.rvn_id, rv.ri
    FROM rv WHERE NOT EXISTS (SELECT 1 FROM weiter w WHERE w.n_id = rv.rvn_id AND w.n_ri = rv.ri)
    UNION ALL
    SELECT k.abschnitt, k.pos + 1, w.n_id, w.n_ri FROM kette k JOIN weiter w ON w.rvn_id = k.rvn_id AND w.ri = k.ri
    WHERE k.pos < 10000
)
SELECT k.abschnitt, k.pos, k.rvn_id, rv.element_nr, k.ri, rv.von, rv.nach, rv.verkehrsrichtung, rv.len,
       coalesce(sum(rv.len) OVER (PARTITION BY k.abschnitt ORDER BY k.pos ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS lage_m,
       rv.geom
FROM kette k JOIN rv ON rv.rvn_id = k.rvn_id AND rv.ri = k.ri;
CREATE INDEX ON abschnitt_kanten (abschnitt);
CREATE INDEX ON abschnitt_kanten (rvn_id, ri);
\echo 'Gerichtete RVN-Kanten ohne Abschnitt (geschlossene Ringe ohne Kreuzung)'
SELECT count(*) FROM rv WHERE NOT EXISTS (SELECT 1 FROM abschnitt_kanten a WHERE a.rvn_id = rv.rvn_id AND a.ri = rv.ri);

CREATE TABLE abschnitte AS
SELECT a.abschnitt, (array_agg(a.von ORDER BY a.pos))[1] AS von, (array_agg(a.nach ORDER BY a.pos DESC))[1] AS nach,
       (array_agg(a.rvn_id ORDER BY a.pos))[1] AS erst_kante, (array_agg(a.rvn_id ORDER BY a.pos DESC))[1] AS letzt_kante,
       count(*)::int AS kanten, sum(a.len) AS len, ST_MakeLine(array_agg(a.geom ORDER BY a.pos)) AS geom
FROM abschnitt_kanten a GROUP BY a.abschnitt;
ALTER TABLE abschnitte ADD PRIMARY KEY (abschnitt);
ALTER TABLE abschnitte ADD COLUMN im_gebiet boolean;
UPDATE abschnitte SET im_gebiet = :radius_m = 0
    OR ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25833), :radius_m);
CREATE INDEX ON abschnitte (von); CREATE INDEX ON abschnitte (nach);
ANALYZE abschnitte;

-- 2. Routen: x -> y über einen Knoten (ohne Wende auf dieselbe RVN-Kante), dazu "allein" für Netzenden
CREATE TABLE routen AS
WITH paar AS (
    SELECT x.abschnitt AS x, y.abschnitt AS y FROM abschnitte x
    JOIN abschnitte y ON y.von = x.nach AND y.erst_kante <> x.letzt_kante
    WHERE (x.im_gebiet OR y.im_gebiet)
      AND NOT EXISTS (SELECT 1 FROM wende w WHERE w.a_id = x.letzt_kante AND w.b_id = y.erst_kante)
), allein AS (
    SELECT s.abschnitt AS x, NULL::int AS y FROM abschnitte s
    WHERE s.im_gebiet AND (NOT EXISTS (SELECT 1 FROM paar p WHERE p.y = s.abschnitt) OR NOT EXISTS (SELECT 1 FROM paar p WHERE p.x = s.abschnitt))
)
SELECT row_number() OVER (ORDER BY z.x, z.y NULLS FIRST)::int AS rid, z.x, z.y,
       ST_StartPoint(ax.geom) AS start, ST_EndPoint(coalesce(ay.geom, ax.geom)) AS ziel,
       ax.geom AS start_linie, coalesce(ay.geom, ax.geom) AS ziel_linie,
       CASE WHEN ay.geom IS NULL THEN ax.geom ELSE ST_MakeLine(ax.geom, ay.geom) END AS linie,
       ST_Buffer(CASE WHEN ay.geom IS NULL THEN ax.geom ELSE ST_MakeLine(ax.geom, ay.geom) END, :korridor_m) AS korridor
FROM (SELECT * FROM paar UNION ALL SELECT * FROM allein) z
JOIN abschnitte ax ON ax.abschnitt = z.x LEFT JOIN abschnitte ay ON ay.abschnitt = z.y;
ALTER TABLE routen ADD PRIMARY KEY (rid);
-- Schnitt zwischen x und y: eine Route x -> y wechselt nur an ihrer Kreuzung b von der Seite von x auf die Seite von y.
-- Die Mittellinie zwischen x und y (gleicher Abstand zu beiden RVN-Linien) beginnt bei b; der richtige Weg kreuzt sie
-- dort, eine Abkürzung woanders (Kreisel und Plätze, Ufer beiderseits eines Kanals, Wende auf die Gegenfahrbahn, parallele
-- Arme wie Charlottenstraße / Markgrafenstraße über eine Querstraße). Kanten, deren Enden auf verschiedenen Seiten liegen,
-- nur im Umkreis :schnitt_m um b; Start- und Zielmenge nur auf der x- bzw. y-Seite. entartet (a-c kürzer als a-b oder
-- b-c) nur zur Auskunft.
ALTER TABLE routen ADD COLUMN kreuzung geometry(Point, 25833), ADD COLUMN entartet boolean;
UPDATE routen SET kreuzung = ST_EndPoint(start_linie),
       entartet = y IS NOT NULL AND (ST_Distance(start, ziel) < ST_Distance(start, ST_EndPoint(start_linie))
                                     OR ST_Distance(start, ziel) < ST_Distance(ST_EndPoint(start_linie), ziel));
\echo 'Entartete Routen (Start und Ziel näher als an der Kreuzung)'
SELECT count(*) FILTER (WHERE entartet) AS entartet, count(*) AS routen FROM routen;

-- virtuelle Kanten: Start -1 -> Knoten der Startmenge, Knoten der Zielmenge -> Ziel -2
CREATE TABLE virt AS
SELECT r.rid, -(row_number() OVER ())::bigint AS id, -1::bigint AS source, k.id AS target,
       ST_LineLocatePoint(r.start_linie, k.geom) * ST_Length(r.start_linie) * :anschluss_faktor + ST_Distance(k.geom, r.start_linie) * :quer_faktor AS cost
FROM routen r JOIN routing_graph.knoten k ON ST_DWithin(k.geom, r.start, :fang_m) AND ST_DWithin(k.geom, r.linie, :korridor_m)
WHERE ST_Distance(k.geom, r.start) < ST_Distance(k.geom, r.ziel)
  AND (r.y IS NULL OR ST_Distance(k.geom, r.start_linie) <= ST_Distance(k.geom, r.ziel_linie))
UNION ALL
SELECT r.rid, -(10000000 + row_number() OVER ())::bigint, k.id, -2,
       (1 - ST_LineLocatePoint(r.ziel_linie, k.geom)) * ST_Length(r.ziel_linie) * :anschluss_faktor + ST_Distance(k.geom, r.ziel_linie) * :quer_faktor
FROM routen r JOIN routing_graph.knoten k ON ST_DWithin(k.geom, r.ziel, :fang_m) AND ST_DWithin(k.geom, r.linie, :korridor_m)
WHERE ST_Distance(k.geom, r.ziel) <= ST_Distance(k.geom, r.start)
  AND (r.y IS NULL OR ST_Distance(k.geom, r.ziel_linie) <= ST_Distance(k.geom, r.start_linie));
CREATE INDEX ON virt (rid);
ANALYZE virt;

-- Korridor je Route, einmal für alle Routen: Kanten des Routing-Graphen, deren Punkte (Stützpunkte, dazu alle 10 m
-- verdichtet) alle höchstens :korridor_m von der Linie der Route entfernt liegen (nahezu gleichwertig zu "ganz im Puffer
-- :korridor_m", ohne das Pufferpolygon, an dem die Prüfung je Aufruf teuer war). Ohne Verdichtung käme eine lange gerade
-- Kante, die einen Bogen der Linie als Sehne abschneidet, mit beiden Enden nah an der Linie in den Korridor, obwohl ihre
-- Mitte weit außerhalb liegt (z. B. 57410012_57420037.02: Wohnstraße 210 m, Mitte 100 m von der Linie). Aufgeteilt nach nächster RVN-Kante: eine Kante gehört nur zu den Routen, deren x
-- oder y die ihr nächste RVN-Kante enthält (sonst gehört sie zum Korridor einer anderen RVN-Straße), außer im Umkreis
-- :schnitt_m um Start, Ziel und Kreuzung, wo mehrere RVN-Arme zusammenkommen. Dazu der Schnitt zwischen x und y (siehe
-- routen): Kanten über die Mittellinie nur im Umkreis :schnitt_m um die Kreuzung.
-- naechste_toleranz_m (> 0): eine Kante gehört auch dann zur Route, wenn ihre Mitte höchstens so viele Meter weiter von der
-- Linie der Route entfernt liegt als von ihrer nächsten RVN-Kante. Sonst fällt z. B. ein Stück des Radstreifens heraus,
-- wenn eine fremde RVN-Kante wenige Meter daneben endet (Heidestraße / Otto-Weidt-Platz: Schutzstreifen 1.5 m von RVN 2488,
-- 6.8 m von der Heidestraße), und die Route weicht auf einen Weg daneben aus.
-- Nächste RVN-Kante je Kante des Routing-Graphen (von der Mitte der Kante aus) mit Abstand
CREATE TABLE naechste_rvn AS
SELECT g.id, n.id AS rvn_id, n.d AS abstand
FROM routing_graph.g g CROSS JOIN LATERAL (
    SELECT r.id, ST_Distance(r.geom, ST_LineInterpolatePoint(g.geom, 0.5)) AS d
    FROM matching.reference_edges r ORDER BY r.geom <-> ST_LineInterpolatePoint(g.geom, 0.5) LIMIT 1) n;
ALTER TABLE naechste_rvn ADD PRIMARY KEY (id);
-- RVN-Kanten je Route (die von x und y)
CREATE TABLE route_rvn AS
SELECT DISTINCT r.rid, k.rvn_id FROM routen r JOIN abschnitt_kanten k ON k.abschnitt IN (r.x, r.y);
CREATE INDEX ON route_rvn (rid, rvn_id);
ANALYZE naechste_rvn, route_rvn;
CREATE TABLE korridor_kanten AS
SELECT r.rid, g.id
FROM routen r JOIN routing_graph.g g ON ST_DWithin(g.geom, r.linie, :korridor_m)
JOIN naechste_rvn n ON n.id = g.id
LEFT JOIN route_rvn rr ON rr.rid = r.rid AND rr.rvn_id = n.rvn_id
CROSS JOIN LATERAL (SELECT bool_and(ST_DWithin(p.geom, r.linie, :korridor_m)) AS drin FROM ST_DumpPoints(ST_Segmentize(g.geom, 10)) p) x
WHERE x.drin
  AND (rr.rid IS NOT NULL OR ST_DWithin(g.geom, r.start, :schnitt_m) OR ST_DWithin(g.geom, r.ziel, :schnitt_m)
       OR ST_DWithin(g.geom, r.kreuzung, :schnitt_m)
       OR (:naechste_toleranz_m > 0 AND ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), r.linie) <= n.abstand + :naechste_toleranz_m))
  AND (r.y IS NULL OR ST_DWithin(g.geom, r.kreuzung, :schnitt_m)
       OR (ST_Distance(ST_StartPoint(g.geom), r.start_linie) - ST_Distance(ST_StartPoint(g.geom), r.ziel_linie))
        * (ST_Distance(ST_EndPoint(g.geom), r.start_linie) - ST_Distance(ST_EndPoint(g.geom), r.ziel_linie)) >= 0);
CREATE INDEX ON korridor_kanten (rid);
ANALYZE korridor_kanten;
-- Fortschrittskosten (wahlweise, :fortschritt; Standard aus, der Abstandsterm ersetzt sie): Lage der Kantenenden entlang der Linie der Route (a, b); eine Kante, die
-- entlang der Linie weiter kommt als sie lang ist, überspringt RVN-Meter und zahlt sie wie ein Anschluss
-- (greatest(|b - a| - Länge, 0) x anschluss_faktor); an der Kreuzung (Umkreis :fortschritt_toleranz_m um den RVN-Knoten
-- zwischen x und y) erst ab :fortschritt_toleranz_m Metern über die Länge hinaus.
\if :fortschritt
ALTER TABLE korridor_kanten ADD COLUMN umweg float8;
UPDATE korridor_kanten k SET umweg = greatest(abs(ST_LineLocatePoint(r.linie, ST_EndPoint(g.geom)) - ST_LineLocatePoint(r.linie, ST_StartPoint(g.geom)))
                                                * ST_Length(r.linie) - g.len
                                              - CASE WHEN r.y IS NOT NULL AND ST_DWithin(g.geom, r.kreuzung, :fortschritt_toleranz_m) THEN :fortschritt_toleranz_m ELSE 0 END, 0)
                                     * :anschluss_faktor
FROM routen r, routing_graph.g g WHERE r.rid = k.rid AND g.id = k.id;
\else
ALTER TABLE korridor_kanten ADD COLUMN umweg float8 DEFAULT 0;
\endif
-- Abstands- und Namensterm wie in der Kandidatenwahl von v7 (HMM: Gauß über den Abstand zur RVN-Linie, Strafe bei
-- abweichendem Straßennamen), je Korridorkante als Zuschlag je Meter (zusatz_je_m):
--   abstand_faktor x (d / abstand_sigma_m)^2  mit d = Abstand der Kantenmitte zur Linie der Route
--   name_faktor, wenn die Kante einen OSM-Namen hat, die ihr nächste RVN-Kante einen Straßennamen und beide verschieden sind
ALTER TABLE korridor_kanten ADD COLUMN zusatz_je_m float8 DEFAULT 0;
SELECT (:abstand_faktor <> 0 OR :name_faktor <> 0) AS abstand_aktiv \gset
\if :abstand_aktiv
CREATE TEMP TABLE name_ungleich AS
SELECT g.id FROM routing_graph.g g JOIN bikegraph.edges be ON be.id = g.id JOIN bikegraph.osm_ways o ON o.way_id = be.way_id
JOIN naechste_rvn n ON n.id = g.id JOIN matching.reference_edges re ON re.id = n.rvn_id
WHERE nullif(o.tags->>'name', '') IS NOT NULL AND nullif(re.strassenname, '') IS NOT NULL AND o.tags->>'name' <> re.strassenname;
CREATE INDEX ON name_ungleich (id);
UPDATE korridor_kanten k SET zusatz_je_m =
       :abstand_faktor * power(ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), r.linie) / :abstand_sigma_m, 2)
     + CASE WHEN u.id IS NOT NULL THEN :name_faktor ELSE 0 END
FROM routen r, routing_graph.g g LEFT JOIN name_ungleich u ON u.id = g.id WHERE r.rid = k.rid AND g.id = k.id;
\endif

-- Kanten-SQL je Route (Korridor, Kosten mit Fortschrittskosten, virtuelle Kanten), für den kürzesten Weg und die Brücken
CREATE TABLE kanten_sql AS
SELECT r.rid, format($q$SELECT g.id, g.source, g.target,
                 CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len * (g.faktor0 + k.zusatz_je_m) + k.umweg END AS cost,
                 CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len * (g.faktor1 + k.zusatz_je_m) + k.umweg END AS reverse_cost
               FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
               UNION ALL SELECT id, source, target, cost, -1 FROM virt WHERE rid = %1$s$q$, r.rid) AS q
FROM routen r;
ALTER TABLE kanten_sql ADD PRIMARY KEY (rid);

-- Ergebnistabellen der Wegsuche (Teil 2 füllt sie parallel)
CREATE TABLE pfad (rid int, seq int, node bigint, edge bigint, cost float8, agg_cost float8);
-- Protokoll der letzten Option über Zusatzkanten (Teil 2 mit zweitlauf): je Route Stufe und Meter je Art
DROP TABLE IF EXISTS zweitlauf;
CREATE TABLE zweitlauf (rid int, stufe text, treppe_m float8, service_m float8, baustelle_m float8);
CREATE INDEX ON pfad (rid);
-- Teilrouten (Teil 2): für Routen ohne Weg je RVN-Kante von x und y (teil = Reihenfolge in Fahrtrichtung), mit oder ohne
-- Weg, mit oder ohne Brücke
-- art und bis_knoten nur mit der Kette (abschnitte_2_kette.sql): weg, bruecke, uebersprungen, ohne; Ankunftsknoten
CREATE TABLE teilroute (rid int, teil int, rvn_id int, ri int, mit_weg boolean, mit_bruecke boolean, art text, bis_knoten bigint,
                        PRIMARY KEY (rid, teil));
-- Brücken über Netzlücken, für Teilrouten ohne Weg: vom Start vorwärts und vom Ziel rückwärts (umgedrehte Kanten)
-- erreichbare Knoten; je Paar a (vom Start erreichbar), b (Ziel von dort erreichbar) im Umkreis :brueck_m die Kosten
-- bis a + Abstand a-b x :brueck_faktor + ab b; das günstigste Paar wird die Brücke. Der Weg ist Start -> a, die Brücke als
-- virtuelle Kante (edge < 0: kein Objekt, zählt weder für Abschnitt noch Kreuzung), b -> Ziel. Eine Brücke je Teilroute.
CREATE TABLE bruecke (rid int, teil int, a bigint, b bigint, laenge float8, kosten_vor float8, kosten_rueck float8,
                      geom geometry(LineString, 25833), teil_ziel int, PRIMARY KEY (rid, teil));
\echo 'Routen, Korridorkanten'
SELECT (SELECT count(*) FROM routen) AS routen, (SELECT count(*) FROM korridor_kanten) AS korridorkanten;
