-- Routing-Graph für das Routing der RVN-Abschnitte (abschnitte.sh): die Kanten des Radnetz-Graphen (bikegraph.edges) im
-- Umkreis :puffer_m um das RVN, ohne Treppen u. ä., mit Faktor, Objekt und Führungsform je Kante und Fahrtrichtung.
-- Faktor je Kante und Richtung (Kosten = Länge x Faktor):
--   radweg_faktor    separater Radweg; TILDA-Weg mit Radinfrastruktur (Führungsform nicht Sonstige Wege)
--   sonstige_faktor  separater Radweg oder TILDA-Weg mit Führungsform Sonstige Wege (Standard 1.3); damit ist
--                    ein Weg mit TILDA-Objekt günstiger als ein Weg ohne Objekt daneben (weg_faktor)
--   streifen_faktor  Straße mit Seitenobjekt (Radstreifen, Schutzstreifen, Busspur u. ä.) in dieser Richtung
--   fahrradstrasse_faktor  Fahrradstraße mit Radzugang in dieser Richtung
--                    (radweg_faktor und fahrradstrasse_faktor Standard rad_faktor = 0.5, streifen_faktor Standard 0.65)
--   1.0        Straße mit Radzugang in dieser Richtung, ohne Seitenobjekt
--   weg_faktor Gehwege, Sonstige Wege, Verbindungen und übrige Wege (Standard 1.5)
--   gesperrt   (NULL) Straße ohne Radzugang und ohne Seitenobjekt in dieser Richtung
-- Danach je Führungsform: Radwegquerungen (Führungsform Kreuzungsweg) bekommen in offenen Richtungen kreuzung_faktor
-- (Standard 0.45; leer: wie Radinfrastruktur oben). Vorrang wie in der Kandidatenwahl von v7 (rules.prefer):
--   bus_faktor             Busspur Rad frei, Radfahrstreifen mit Linienverkehr frei (v7: vor unbeschildertem Radweg)
--   geschuetzt_faktor      Geschützter Radfahrstreifen (v7: vor Busspur)
--   radweg_zeichen_faktor  Radweg mit Zeichen 237, 240 oder 241 (v7: verliert nicht gegen die Busspur)
-- (Standard 0.45, 0.4, 0.4; leer: keine Änderung).
-- Nichts ist gefaltet: Radstreifen zählen auf ihrer Straße (bl_faltung, durchgang definiert), separate Radwege auf ihrer
-- eigenen Kante.
-- Inseln entfernt: es bleibt die größte Zusammenhangskomponente der offenen Kanten (ungerichtet). Sonst beginnt und endet
-- eine Route über die virtuellen Kanten auf einer Insel, z. B. den Gehwegen in der Mitte des Großen Sterns, die nur über
-- Treppen in Tunneln erreichbar sind. Die Komponenten werden auf dem ganzen Netz bestimmt, erst danach wird auf den
-- Umkreis um das RVN beschränkt: ein Gebiet, das nur über Straßen außerhalb des Umkreises angebunden ist (z. B. das
-- Köpenicker Spreeufer am Spreetunnel mit Treppen), ist keine Insel.
-- Zusatzkanten für den zweiten Lauf (abschnitte_2c_zweitlauf.sql): Treppen und Aufzüge sowie Erschließungsstraßen
-- außerhalb des TILDA-Routings (Netz D, highway=service, nicht privat oder gesperrt) sowie Baustellen (highway=construction,
-- außer Autobahn- und Kraftfahrstraßenbaustellen). Im normalen Lauf gesperrt (Faktor
-- NULL), im zweiten Lauf mit faktor_plus (treppe_faktor, service_faktor bzw. baustelle_faktor), gekennzeichnet in zusatz. Die Inselprüfung
-- entfernt sie nicht (sie sind gesperrt und gehören zu keiner Komponente offener Kanten).
-- Eingang: bikegraph.edges, bl_input, bl_faltung, dc_input, input_edges; matching.reference_edges (RVN)
-- Ausgang (Schema routing_graph): g (Graph; mit versatz0/versatz1 der Seitenobjekte aus TILDA, siehe unten), knoten
-- (Knoten mit Lage)
-- psql-Variablen: puffer_m (Standard 200), rad_faktor (Standard 0.5), radweg_faktor, streifen_faktor (Standard 0.65),
-- fahrradstrasse_faktor (Standard rad_faktor), sonstige_faktor (Standard 1.3), weg_faktor (Standard 1.5), kreuzung_faktor
-- (Standard 0.45), bus_faktor (Standard 0.45), geschuetzt_faktor (Standard 0.4), radweg_zeichen_faktor (Standard 0.4),
-- treppe_faktor (Standard 3.0), service_faktor (Standard 1.5), baustelle_faktor (Standard 3.0)
\if :{?puffer_m} \else \set puffer_m 200 \endif
\if :{?rad_faktor} \else \set rad_faktor 0.5 \endif
\if :{?radweg_faktor} \else \set radweg_faktor :rad_faktor \endif
\if :{?streifen_faktor} \else \set streifen_faktor 0.65 \endif
\if :{?fahrradstrasse_faktor} \else \set fahrradstrasse_faktor :rad_faktor \endif
\if :{?sonstige_faktor} \else \set sonstige_faktor 1.3 \endif
\if :{?kreuzung_faktor} \else \set kreuzung_faktor 0.45 \endif
\if :{?bus_faktor} \else \set bus_faktor 0.45 \endif
\if :{?geschuetzt_faktor} \else \set geschuetzt_faktor 0.4 \endif
\if :{?radweg_zeichen_faktor} \else \set radweg_zeichen_faktor 0.4 \endif
\if :{?weg_faktor} \else \set weg_faktor 1.5 \endif
\if :{?treppe_faktor} \else \set treppe_faktor 3.0 \endif
\if :{?service_faktor} \else \set service_faktor 1.5 \endif
\if :{?baustelle_faktor} \else \set baustelle_faktor 3.0 \endif
CREATE EXTENSION IF NOT EXISTS pgrouting;
DROP SCHEMA IF EXISTS routing_graph CASCADE;
CREATE SCHEMA routing_graph;

-- Führungsform je TILDA-Objekt
CREATE TEMP TABLE fuehr_je_objekt AS
SELECT DISTINCT ON (input_ref) input_ref, attrs->>'fuehr' AS fuehr FROM bikegraph.input_edges ORDER BY input_ref, id;
CREATE INDEX ON fuehr_je_objekt (input_ref);
-- Seitenobjekte je Straßenkante und Richtung
CREATE TEMP TABLE seite AS
SELECT f.strassen_kante AS kante, f.ri, min(i.input_ref) AS input_ref
FROM bikegraph.bl_faltung f JOIN bikegraph.bl_input i ON i.id = f.input_id WHERE f.durchgang = 'definiert' GROUP BY 1, 2;
CREATE INDEX ON seite (kante, ri);
-- Kanten des ganzen Netzes ohne Treppen u. ä. (für die Inseln), davon die im Umkreis um das RVN
CREATE TEMP TABLE alle AS
SELECT e.id FROM bikegraph.edges e LEFT JOIN bikegraph.osm_ways o ON o.way_id = e.way_id
WHERE e.len > 0 AND coalesce(e.highway, '') NOT IN ('proposed', 'corridor', 'platform')
  -- Baustellen bleiben als Zusatzkanten (unten), außer an Autobahnen und Kraftfahrstraßen
  AND NOT (e.highway = 'construction' AND coalesce(o.tags->>'construction', '') ~ '^(motorway|trunk)');
CREATE INDEX ON alle (id);
CREATE TEMP TABLE nah AS
SELECT DISTINCT a.id FROM alle a JOIN bikegraph.edges e ON e.id = a.id JOIN matching.reference_edges r ON ST_DWithin(e.geom, r.geom, :puffer_m);
CREATE INDEX ON nah (id);
ANALYZE alle, nah;

CREATE TABLE routing_graph.g AS
WITH art AS (
    SELECT e.*, l.input_ref AS radweg, fl.fuehr AS radweg_fuehr, w.input_ref AS weg, fw.fuehr AS weg_fuehr, fs.fuehr AS strasse_fuehr,
           s0.input_ref AS seite0, s1.input_ref AS seite1,
           (e.herkunft = 'fahrbahn' AND w.input_ref IS NULL) AS strasse
    FROM alle JOIN bikegraph.edges e ON e.id = alle.id
    LEFT JOIN bikegraph.bl_input l ON l.id = e.id AND l.art = 'separat'
    LEFT JOIN bikegraph.dc_input w ON w.kante = e.id AND w.art = 'weg'
    LEFT JOIN fuehr_je_objekt fw ON fw.input_ref = w.input_ref
    LEFT JOIN fuehr_je_objekt fs ON fs.input_ref = e.routing_id
    LEFT JOIN fuehr_je_objekt fl ON fl.input_ref = l.input_ref
    LEFT JOIN seite s0 ON s0.kante = e.id AND s0.ri = 0
    LEFT JOIN seite s1 ON s1.kante = e.id AND s1.ri = 1
), richtung AS (
    SELECT a.*, d.ri,
           CASE WHEN d.ri = 0 THEN a.fwd ELSE a.bwd END AS rad, CASE WHEN d.ri = 0 THEN a.way_fwd ELSE a.way_bwd END AS weg_offen,
           CASE WHEN d.ri = 0 THEN a.seite0 ELSE a.seite1 END AS seite_obj
    FROM art a, (VALUES (0), (1)) d(ri)
), bewertet AS (
    SELECT r.*,
           CASE
             WHEN r.radweg IS NOT NULL THEN CASE WHEN NOT (r.rad OR NOT a_any) THEN NULL
                                                 WHEN r.radweg_fuehr = 'Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)' THEN :sonstige_faktor
                                                 ELSE :radweg_faktor END
             WHEN r.strasse AND r.seite_obj IS NOT NULL THEN :streifen_faktor
             WHEN r.strasse AND r.rad AND r.strasse_fuehr = 'Fahrradstraße /-zone (Z 244)' THEN :fahrradstrasse_faktor
             WHEN r.strasse AND r.rad THEN 1.0
             WHEN r.strasse THEN NULL
             WHEN r.weg IS NOT NULL AND r.weg_fuehr IS DISTINCT FROM 'Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)'
                  AND (r.rad OR r.weg_offen) THEN :radweg_faktor
             WHEN r.weg IS NOT NULL AND (r.rad OR r.weg_offen OR NOT a_any) THEN :sonstige_faktor
             WHEN r.rad OR r.weg_offen OR NOT a_any THEN :weg_faktor
           END AS faktor,
           CASE
             WHEN r.radweg IS NOT NULL THEN r.radweg
             WHEN r.strasse AND r.seite_obj IS NOT NULL THEN r.seite_obj
             WHEN r.strasse AND r.rad THEN r.routing_id
             WHEN r.weg IS NOT NULL THEN r.weg
           END AS objekt
    FROM (SELECT x.*, (x.fwd OR x.bwd OR x.way_fwd OR x.way_bwd) AS a_any FROM richtung x) r
)
SELECT b0.id, b0.source, b0.target, b0.len, b0.herkunft, b0.highway, b0.routing_id,
       b0.faktor AS faktor0, b1.faktor AS faktor1, b0.objekt AS objekt0, b1.objekt AS objekt1,
       f0.fuehr AS fuehr0, f1.fuehr AS fuehr1,
       -- Objekt der Richtung ist ein Seitenobjekt auf dieser Straßenkante (Versatz unten)
       (b0.radweg IS NULL AND b0.strasse AND b0.seite_obj IS NOT NULL) AS seitenobjekt0,
       (b1.radweg IS NULL AND b1.strasse AND b1.seite_obj IS NOT NULL) AS seitenobjekt1, b0.geom
FROM bewertet b0 JOIN bewertet b1 ON b1.id = b0.id AND b1.ri = 1
LEFT JOIN fuehr_je_objekt f0 ON f0.input_ref = b0.objekt LEFT JOIN fuehr_je_objekt f1 ON f1.input_ref = b1.objekt
WHERE b0.ri = 0;
ALTER TABLE routing_graph.g ADD PRIMARY KEY (id);

-- Faktor je Führungsform: Querungen
\if :{?kreuzung_faktor}
SELECT :'kreuzung_faktor' <> '' AS mit_kreuzung_faktor \gset
\if :mit_kreuzung_faktor
UPDATE routing_graph.g SET faktor0 = CASE WHEN faktor0 IS NOT NULL AND fuehr0 = 'Kreuzungsweg' THEN :kreuzung_faktor ELSE faktor0 END,
                           faktor1 = CASE WHEN faktor1 IS NOT NULL AND fuehr1 = 'Kreuzungsweg' THEN :kreuzung_faktor ELSE faktor1 END
WHERE fuehr0 = 'Kreuzungsweg' OR fuehr1 = 'Kreuzungsweg';
\endif
\endif

-- Vorrang wie in v7 (wahlweise): Busspur, geschützter Radfahrstreifen, beschilderter Radweg
CREATE TEMP TABLE zeichen AS
SELECT DISTINCT input_ref FROM bikegraph.input_edges WHERE attrs->>'tilda_traffic_sign' ~ '(^|[^0-9])(237|240|241)';
CREATE INDEX ON zeichen (input_ref);
SELECT :'bus_faktor' <> '' AS mit_bus, :'geschuetzt_faktor' <> '' AS mit_geschuetzt, :'radweg_zeichen_faktor' <> '' AS mit_zeichen \gset
\if :mit_bus
UPDATE routing_graph.g SET
    faktor0 = CASE WHEN faktor0 IS NOT NULL AND (fuehr0 LIKE 'Bussonderfahrstreifen%' OR fuehr0 LIKE 'Radfahrstreifen mit Linienverkehr%') THEN :bus_faktor ELSE faktor0 END,
    faktor1 = CASE WHEN faktor1 IS NOT NULL AND (fuehr1 LIKE 'Bussonderfahrstreifen%' OR fuehr1 LIKE 'Radfahrstreifen mit Linienverkehr%') THEN :bus_faktor ELSE faktor1 END
WHERE fuehr0 LIKE 'Bussonderfahrstreifen%' OR fuehr1 LIKE 'Bussonderfahrstreifen%' OR fuehr0 LIKE 'Radfahrstreifen mit Linienverkehr%' OR fuehr1 LIKE 'Radfahrstreifen mit Linienverkehr%';
\endif
\if :mit_geschuetzt
UPDATE routing_graph.g SET
    faktor0 = CASE WHEN faktor0 IS NOT NULL AND fuehr0 = 'Geschützter Radfahrstreifen' THEN :geschuetzt_faktor ELSE faktor0 END,
    faktor1 = CASE WHEN faktor1 IS NOT NULL AND fuehr1 = 'Geschützter Radfahrstreifen' THEN :geschuetzt_faktor ELSE faktor1 END
WHERE fuehr0 = 'Geschützter Radfahrstreifen' OR fuehr1 = 'Geschützter Radfahrstreifen';
\endif
\if :mit_zeichen
UPDATE routing_graph.g g SET
    faktor0 = CASE WHEN g.faktor0 IS NOT NULL AND g.fuehr0 = 'Radweg' AND z0.input_ref IS NOT NULL THEN :radweg_zeichen_faktor ELSE g.faktor0 END,
    faktor1 = CASE WHEN g.faktor1 IS NOT NULL AND g.fuehr1 = 'Radweg' AND z1.input_ref IS NOT NULL THEN :radweg_zeichen_faktor ELSE g.faktor1 END
FROM routing_graph.g x LEFT JOIN zeichen z0 ON z0.input_ref = x.objekt0 LEFT JOIN zeichen z1 ON z1.input_ref = x.objekt1
WHERE x.id = g.id AND (x.fuehr0 = 'Radweg' OR x.fuehr1 = 'Radweg') AND (z0.input_ref IS NOT NULL OR z1.input_ref IS NOT NULL);
\endif

-- Schutzstreifen an Bushaltestellen wie in v7 (processing/helpers/convert_schutzstreifen_at_bus_stops.py): ein
-- Schutzstreifen-Objekt (je Kantenrichtung, objekt0/objekt1) wird Radfahrstreifen, wenn eine Haltestelle bis :halt_m (20 m)
-- rechts in Fahrtrichtung neben einer seiner Kanten liegt und es in Fahrtrichtung an einen Radfahrstreifen grenzt (an seinem
-- Ende geht ein Radfahrstreifen weiter oder an seinem Anfang endet einer). Der Faktor bleibt (beide streifen_faktor).
-- Haltestellen aus bikegraph.bus_stops (processing/output/bus_stops_on_rvn.fgb, geladen mit ogr2ogr -nln bikegraph.bus_stops
-- -t_srs EPSG:25833 -lco GEOMETRY_NAME=geom); fehlt die Tabelle, entfällt der Schritt.
\if :{?halt_m} \else \set halt_m 20 \endif
SELECT to_regclass('bikegraph.bus_stops') IS NOT NULL AS mit_halt \gset
\if :mit_halt
CREATE TEMP TABLE streifen AS
SELECT g.id, d.ri, CASE WHEN d.ri = 0 THEN g.fuehr0 ELSE g.fuehr1 END AS fuehr,
       coalesce(CASE WHEN d.ri = 0 THEN g.objekt0 ELSE g.objekt1 END, 'kante:' || g.id || ':' || d.ri) AS objekt,
       CASE WHEN d.ri = 0 THEN g.source ELSE g.target END AS von, CASE WHEN d.ri = 0 THEN g.target ELSE g.source END AS nach,
       CASE WHEN d.ri = 0 THEN g.geom ELSE ST_Reverse(g.geom) END AS geom
FROM routing_graph.g g, (VALUES (0), (1)) d(ri)
WHERE CASE WHEN d.ri = 0 THEN g.fuehr0 ELSE g.fuehr1 END IN ('Schutzstreifen', 'Radfahrstreifen')
  AND CASE WHEN d.ri = 0 THEN g.faktor0 ELSE g.faktor1 END IS NOT NULL;
CREATE INDEX ON streifen USING gist (geom);
-- Schutzstreifen-Objekte mit Haltestelle rechts (Kreuzprodukt der Fahrtrichtung am nächsten Punkt < 0)
CREATE TEMP TABLE halt_objekt AS
SELECT DISTINCT s.objekt FROM streifen s JOIN bikegraph.bus_stops b ON ST_DWithin(b.geom, s.geom, :halt_m)
CROSS JOIN LATERAL (SELECT ST_LineLocatePoint(s.geom, b.geom) AS t) l
CROSS JOIN LATERAL (SELECT ST_LineInterpolatePoint(s.geom, greatest(0, l.t - 0.05)) AS q1, ST_LineInterpolatePoint(s.geom, least(1, l.t + 0.05)) AS q2) q
WHERE s.fuehr = 'Schutzstreifen'
  AND (ST_X(q.q2) - ST_X(q.q1)) * (ST_Y(b.geom) - ST_Y(q.q1)) - (ST_Y(q.q2) - ST_Y(q.q1)) * (ST_X(b.geom) - ST_X(q.q1)) < 0;
-- davon die, die in Fahrtrichtung an einen Radfahrstreifen grenzen
CREATE TEMP TABLE halt_umwandeln AS
SELECT DISTINCT s.objekt FROM streifen s JOIN halt_objekt h ON h.objekt = s.objekt
JOIN streifen r ON r.fuehr = 'Radfahrstreifen' AND (r.von = s.nach OR r.nach = s.von)
WHERE s.fuehr = 'Schutzstreifen';
UPDATE routing_graph.g g SET
    fuehr0 = CASE WHEN g.fuehr0 = 'Schutzstreifen' AND coalesce(g.objekt0, 'kante:' || g.id || ':0') IN (SELECT objekt FROM halt_umwandeln) THEN 'Radfahrstreifen' ELSE g.fuehr0 END,
    fuehr1 = CASE WHEN g.fuehr1 = 'Schutzstreifen' AND coalesce(g.objekt1, 'kante:' || g.id || ':1') IN (SELECT objekt FROM halt_umwandeln) THEN 'Radfahrstreifen' ELSE g.fuehr1 END
WHERE g.fuehr0 = 'Schutzstreifen' OR g.fuehr1 = 'Schutzstreifen';
\echo 'Schutzstreifen an Bushaltestellen: Objekte mit Haltestelle rechts, davon an Radfahrstreifen grenzend (umgewandelt)'
SELECT (SELECT count(*) FROM halt_objekt) AS mit_haltestelle, (SELECT count(*) FROM halt_umwandeln) AS umgewandelt;
\endif

-- Zusatzkanten für den zweiten Lauf: im normalen Lauf gesperrt
ALTER TABLE routing_graph.g ADD COLUMN zusatz text, ADD COLUMN faktor_plus float8;
UPDATE routing_graph.g SET faktor0 = NULL, faktor1 = NULL, zusatz = 'treppe', faktor_plus = :treppe_faktor
WHERE highway IN ('steps', 'elevator');
UPDATE routing_graph.g g SET zusatz = 'service', faktor_plus = :service_faktor
FROM bikegraph.edges e LEFT JOIN bikegraph.osm_ways o ON o.way_id = e.way_id
WHERE e.id = g.id AND g.highway = 'service' AND e.netz = 'D' AND g.faktor0 IS NULL AND g.faktor1 IS NULL
  AND coalesce(o.tags->>'access', '') NOT IN ('private', 'no') AND coalesce(o.tags->>'bicycle', '') <> 'no';
UPDATE routing_graph.g SET faktor0 = NULL, faktor1 = NULL, zusatz = 'baustelle', faktor_plus = :baustelle_faktor
WHERE highway = 'construction';

-- Ausdrücklich für den Radverkehr freigegeben (OSM bicycle=yes oder designated, nicht access/bicycle=private): offen im
-- normalen Lauf in den Richtungen, die OSM erlaubt (way_fwd/way_bwd, mit Einbahnregeln), auch ohne TILDA-Objekt, z. B.
-- Feuerwehrzufahrten am Ende gesperrter Straßen (Courbièrestraße / An der Urania). Fahrbahn mit Faktor 1.0 wie eine Straße
-- mit Radzugang, sonst weg_faktor; keine Zusatzkante mehr. Treppen und Aufzüge bleiben Zusatzkanten (nicht fahrbar).
-- Nur ganz gesperrte Kanten: eine Kante, die in einer Richtung offen ist (Einrichtungsradweg laut TILDA), bekommt die
-- Gegenrichtung nicht aus OSM.
UPDATE routing_graph.g g SET
    faktor0 = CASE WHEN e.way_fwd THEN CASE WHEN e.herkunft = 'fahrbahn' THEN 1.0 ELSE :weg_faktor END END,
    faktor1 = CASE WHEN e.way_bwd THEN CASE WHEN e.herkunft = 'fahrbahn' THEN 1.0 ELSE :weg_faktor END END,
    zusatz = NULL, faktor_plus = NULL
FROM bikegraph.edges e JOIN bikegraph.osm_ways o ON o.way_id = e.way_id
WHERE e.id = g.id AND g.faktor0 IS NULL AND g.faktor1 IS NULL AND (e.way_fwd OR e.way_bwd)
  AND o.tags->>'bicycle' IN ('yes', 'designated') AND coalesce(o.tags->>'access', '') <> 'private'
  AND coalesce(g.highway, '') NOT IN ('steps', 'elevator');

-- Inseln entfernen: alles außer der größten Zusammenhangskomponente der offenen Kanten
CREATE TEMP TABLE komp AS
SELECT * FROM pgr_connectedComponents('SELECT id, source, target, 1.0 AS cost, 1.0 AS reverse_cost FROM routing_graph.g WHERE faktor0 IS NOT NULL OR faktor1 IS NOT NULL');
CREATE INDEX ON komp (node);
CREATE TEMP TABLE haupt AS SELECT node FROM komp WHERE component = (SELECT component FROM komp GROUP BY 1 ORDER BY count(*) DESC LIMIT 1);
CREATE INDEX ON haupt (node);
\echo 'Inseln entfernt (ganzes Netz, davon im Umkreis um das RVN)'
WITH weg AS (DELETE FROM routing_graph.g g WHERE g.zusatz IS NULL AND NOT EXISTS (SELECT 1 FROM haupt h WHERE h.node = g.source) RETURNING g.id, g.len)
SELECT count(*) AS kanten, round(sum(len)::numeric / 1000, 1) AS km,
       count(*) FILTER (WHERE id IN (SELECT id FROM nah)) AS kanten_umkreis,
       round(coalesce(sum(len) FILTER (WHERE id IN (SELECT id FROM nah)), 0)::numeric / 1000, 1) AS km_umkreis FROM weg;
-- erst jetzt auf den Umkreis um das RVN beschränken
DELETE FROM routing_graph.g g WHERE NOT EXISTS (SELECT 1 FROM nah n WHERE n.id = g.id);
CREATE INDEX ON routing_graph.g USING gist (geom);
ANALYZE routing_graph.g;

-- Versatz der Seitenobjekte (Radfahrstreifen, Schutzstreifen, Busspur u. ä.) aus TILDA: public.routing tags.offset
-- (tilda-geo extract_bikelanes: halbe Straßenbreite, + links / - rechts der Linie der Routing-Zeile). Die Kanten liegen
-- auf der Straßenmittellinie; versatz0/versatz1 ist der Versatz des Objekts in Fahrtrichtung der Kantenrichtung
-- (ri 0: in Zeichenrichtung, ri 1: dagegen), + links / - rechts. Die Richtung der Kante gegen die Linie der
-- Routing-Zeile wird aus der Geometrie bestimmt (Lage zweier Punkte der Kante auf der Linie), nicht aus der Seite.
-- Nur für Straßenkanten mit Seitenobjekt (objekt = seite_obj); separate Wege und Straßen ohne Objekt bleiben NULL.
-- Gebraucht erst in abschnitte_5_versatz.sql (Nachbearbeitung der Routen), nicht in den Kosten.
ALTER TABLE routing_graph.g ADD COLUMN versatz0 float8, ADD COLUMN versatz1 float8;
CREATE TEMP TABLE tilda_versatz AS
SELECT DISTINCT ON (tags->>'source_id') tags->>'source_id' AS objekt, (tags->>'offset')::float8 AS versatz,
       ST_Transform(geom, 25833) AS geom
FROM public.routing
WHERE tags->>'source_table' = 'bikelanes' AND tags->>'side' IN ('left', 'right')
  AND tags->>'offset' ~ '^\s*[-+]?[0-9]+(\.[0-9]*)?\s*$' AND (tags->>'offset')::float8 <> 0
ORDER BY tags->>'source_id', id;
CREATE INDEX ON tilda_versatz (objekt);
ANALYZE tilda_versatz;
WITH je_richtung AS (
    SELECT g.id, d.ri, t.versatz,
           -- Kante in Richtung der Routing-Linie: ihr Punkt bei 1/4 liegt auf der Linie vor dem bei 3/4
           ST_LineLocatePoint(t.geom, ST_LineInterpolatePoint(g.geom, 0.25))
             <= ST_LineLocatePoint(t.geom, ST_LineInterpolatePoint(g.geom, 0.75)) AS gleich
    FROM routing_graph.g g
    CROSS JOIN LATERAL (VALUES (0, g.objekt0, g.seitenobjekt0), (1, g.objekt1, g.seitenobjekt1)) d(ri, objekt, seite)
    JOIN tilda_versatz t ON t.objekt = d.objekt
    WHERE d.seite AND ST_DWithin(ST_LineInterpolatePoint(g.geom, 0.5), t.geom, 1.0)
)
UPDATE routing_graph.g g SET
    versatz0 = (SELECT CASE WHEN j.gleich THEN j.versatz ELSE -j.versatz END FROM je_richtung j WHERE j.id = g.id AND j.ri = 0),
    -- ri 1 fährt gegen die Zeichenrichtung: links und rechts tauschen
    versatz1 = (SELECT CASE WHEN j.gleich THEN -j.versatz ELSE j.versatz END FROM je_richtung j WHERE j.id = g.id AND j.ri = 1)
WHERE g.id IN (SELECT id FROM je_richtung);
\echo 'Versatz der Seitenobjekte aus TILDA (public.routing tags.offset): Objekte mit Versatz, Kantenrichtungen mit Objekt, davon mit Versatz'
SELECT (SELECT count(*) FROM tilda_versatz) AS objekte_mit_versatz,
       count(*) FILTER (WHERE seitenobjekt0) + count(*) FILTER (WHERE seitenobjekt1) AS richtungen_mit_objekt,
       count(versatz0) + count(versatz1) AS mit_versatz,
       round(avg(abs(coalesce(versatz0, versatz1)))::numeric, 1) AS mittel_m
FROM routing_graph.g;

CREATE TABLE routing_graph.knoten AS
SELECT DISTINCT ON (k) k AS id, p AS geom FROM (
    SELECT source AS k, ST_StartPoint(geom) AS p FROM routing_graph.g UNION ALL SELECT target, ST_EndPoint(geom) FROM routing_graph.g) x
ORDER BY k;
ALTER TABLE routing_graph.knoten ADD PRIMARY KEY (id);
CREATE INDEX ON routing_graph.knoten USING gist (geom);
ANALYZE routing_graph.knoten;

\echo 'Routing-Graph'
SELECT count(*) AS kanten, round(sum(len)::numeric / 1000) AS km,
       count(*) FILTER (WHERE faktor0 IS NULL AND faktor1 IS NULL) AS gesperrt,
       count(*) FILTER (WHERE least(faktor0, faktor1) < 1) AS radinfrastruktur,
       count(*) FILTER (WHERE zusatz = 'treppe') AS zusatz_treppe, count(*) FILTER (WHERE zusatz = 'service') AS zusatz_service,
       count(*) FILTER (WHERE zusatz = 'baustelle') AS zusatz_baustelle
FROM routing_graph.g;
