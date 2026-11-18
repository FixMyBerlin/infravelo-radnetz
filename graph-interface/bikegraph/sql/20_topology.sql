-- Schritt 2: Gesamtgraph aus den OSM-Knoten, je Stück zwischen zwei echten Knoten eine Kante, mit Herkunft.
-- Voraussetzung: osm_nodes.py (bikegraph.osm_ways, osm_way_nodes, osm_nodes), tilda-geo public.routing (Richtungen,
-- Kategorien, Seitenobjekte) und public.roads, public.bikelanes, public."roadsPathClasses" (nur volle Tags je Objekt).
-- Ausgang:
--   bikegraph.edges         id, way_id, seg, source, target (OSM-Knoten-ids), herkunft, highway, routing_id,
--                           fwd/bwd (Radverkehr erlaubt in/gegen OSM-Knotenreihenfolge), len, geom (EPSG:25833)
--   bikegraph.side_objects  Seitenobjekte (Streifen aus der Mittellinien-Kartierung) je Elternweg und Seite,
--                           fwd/bwd bezogen auf die Knotenreihenfolge des Elternwegs
-- Netz (Spalte netz) und Herkunft: R routing-Fahrbahnen und D übrige Fahrwege -> fahrbahn; S routing bikelanes/
-- roadsPathClasses -> separat; C übrige -> verbindung (nur Topologie). routing_id = TILDA-id des Wegs (R, S), sonst leer.
--                           way_fwd/way_bwd (Rad darf die Fahrbahn so befahren), kfz_fwd/kfz_bwd (Kfz-Richtungen)
BEGIN;
DROP TABLE IF EXISTS bikegraph.edges, bikegraph.side_objects, bikegraph.real_nodes;

-- Echte Knoten: Wegenden, Knoten in mehr als einem Weg, Knoten, die ein Weg mehrfach besucht
CREATE TABLE bikegraph.real_nodes AS
SELECT node_id FROM bikegraph.osm_way_nodes GROUP BY node_id HAVING count(DISTINCT way_id) > 1 OR count(*) > 1
UNION
SELECT node_id FROM bikegraph.osm_way_nodes wn
WHERE seq = 0 OR seq = (SELECT max(seq) FROM bikegraph.osm_way_nodes x WHERE x.way_id = wn.way_id);
ALTER TABLE bikegraph.real_nodes ADD PRIMARY KEY (node_id);

CREATE TEMP TABLE pts ON COMMIT DROP AS
SELECT wn.way_id, wn.seq, wn.node_id, (rn.node_id IS NOT NULL) AS cut,
       ST_Transform(ST_SetSRID(ST_MakePoint(n.lon, n.lat), 4326), 25833) AS p
FROM bikegraph.osm_way_nodes wn
JOIN bikegraph.osm_nodes n ON n.node_id = wn.node_id
LEFT JOIN bikegraph.real_nodes rn ON rn.node_id = wn.node_id;

-- Stücknummer eines Punkts: Anzahl der Schnitte vor ihm (der erste Punkt ist immer ein Schnitt, also ab 1).
-- Ein Schnittpunkt beendet sein Stück und beginnt das nächste.
CREATE TEMP TABLE pts_seg ON COMMIT DROP AS
SELECT way_id, seq, node_id, p, cut,
       COALESCE(sum(CASE WHEN cut THEN 1 ELSE 0 END) OVER (PARTITION BY way_id ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS seg
FROM pts;

CREATE TEMP TABLE segs ON COMMIT DROP AS
SELECT way_id, seg, (array_agg(node_id ORDER BY seq))[1] AS source, (array_agg(node_id ORDER BY seq DESC))[1] AS target,
       ST_MakeLine(p ORDER BY seq) AS geom
FROM (
    SELECT way_id, seq, node_id, p, seg FROM pts_seg
    UNION ALL
    SELECT way_id, seq, node_id, p, seg + 1 FROM pts_seg WHERE cut
) x
GROUP BY way_id, seg
HAVING count(*) >= 2;

-- TILDA-Objekte aus dem Routing-Export (public.routing, tilda-geo routing_infra): eine Zeile je Quellobjekt (Fahrbahn,
-- Weg, linker/rechter Streifen). Richtung: oneway = yes heißt, die Geometrie zeigt in die erlaubte Richtung (oneway=-1
-- ist dort schon umgedreht); oneway_motor = yes heißt Kfz einrichtig, Rad beidseitig (Geometrie in Kfz-Richtung).
-- Autobahnen, Kraftfahrstraßen, bicycle=no und Gehwege fehlen in routing; sie bleiben Topologie (D/C).
-- Volle Tags über source_table/source_id aus der jeweiligen Tabelle (für Kategorie, road, adjoining_road, ...).
CREATE TEMP TABLE tilda ON COMMIT DROP AS
SELECT r.tags->>'source_id' AS id, r.osm_id, r.tags->>'source_table' AS src, coalesce(r.tags->>'side', 'self') AS side,
       coalesce(q.tags, '{}'::jsonb) || jsonb_strip_nulls(jsonb_build_object(
           'category', r.tags->>'category', 'road', r.tags->>'road',
           'routing_oneway', r.tags->>'oneway', 'oneway_motor', r.tags->>'oneway_motor')) AS tags,
       ST_Transform(r.geom, 25833) AS g,
       r.tags->>'oneway' = 'yes' AS oneway,
       r.tags->>'oneway' = 'yes' OR r.tags->>'oneway_motor' = 'yes' AS kfz_oneway,
       CASE r.tags->>'source_table' WHEN 'roads' THEN 1 WHEN 'bikelanes' THEN 2 ELSE 3 END AS prio
FROM public.routing r
LEFT JOIN LATERAL (
    SELECT x.tags FROM public.roads x WHERE r.tags->>'source_table' = 'roads' AND x.id = r.tags->>'source_id'
    UNION ALL SELECT x.tags FROM public.bikelanes x WHERE r.tags->>'source_table' = 'bikelanes' AND x.id = r.tags->>'source_id'
    UNION ALL SELECT x.tags FROM public."roadsPathClasses" x
              WHERE r.tags->>'source_table' = 'roadsPathClasses' AND x.id = r.tags->>'source_id'
    LIMIT 1) q ON true;
CREATE INDEX ON tilda (id);
CREATE INDEX ON tilda (osm_id);
-- für die folgenden Schritte (Tags je TILDA-id): eine Zeile je id
DROP TABLE IF EXISTS bikegraph.tilda;
CREATE TABLE bikegraph.tilda AS
SELECT DISTINCT ON (id) id, osm_id, src AS source_table, tags FROM tilda ORDER BY id, prio;
ALTER TABLE bikegraph.tilda ADD PRIMARY KEY (id);

-- Richtung jeder Geometrie gegenüber der Knotenreihenfolge des OSM-Wegs. Vergleich des Anfangspunkts mit dem ersten
-- Knoten; bei geschlossenen Wegen des zweiten Punkts.
CREATE TEMP TABLE tilda_dir ON COMMIT DROP AS
SELECT t.id, t.side,
       CASE WHEN ST_DWithin(ST_StartPoint(t.g), ST_EndPoint(t.g), 0.05)
            THEN NOT ST_DWithin(ST_PointN(t.g, 2), p1.p, 0.5)
            ELSE NOT ST_DWithin(ST_StartPoint(t.g), p0.p, 0.5) END AS rev
FROM tilda t
JOIN pts p0 ON p0.way_id = t.osm_id AND p0.seq = 0
JOIN pts p1 ON p1.way_id = t.osm_id AND p1.seq = 1;
CREATE INDEX ON tilda_dir (id, side);

-- Netze (Teilgraphen), alle auf denselben OSM-Knoten; maßgeblich ist das Objekt des Wegs selbst (side = self):
--   R  routing roads, oder routing bikelanes auf einer Kfz-Straße (Fahrradstraße, Fußgängerzone) -> herkunft fahrbahn
--   S  routing bikelanes mit eigener Geometrie ∪ roadsPathClasses                                  -> herkunft separat
--   D  übrige Fahrwege ohne routing-Zeile (Zufahrten, Service, Autobahn, bicycle=no)               -> herkunft fahrbahn
--   C  alles übrige (Gehwege, Querungen ohne Radfreigabe, ...)                                     -> herkunft verbindung
-- Radverkehr auf der Fahrbahn selbst: nicht bei bicycle=no oder use_sidepath (Radweg benutzungspflichtig). Die Kante
-- bleibt Faltziel und kommt in den Radnetz-Graphen, wo etwas auf sie gefaltet ist (sql/40_network.sql).
-- way_fwd/way_bwd: Richtungen, in denen ein Rad die Fahrbahn befahren darf, unabhängig vom Radzugang (routing oneway);
-- kfz_fwd/kfz_bwd: Kfz-Richtungen (zusätzlich oneway_motor).
CREATE TEMP TABLE way_class ON COMMIT DROP AS
SELECT w.way_id, w.tags->>'highway' AS highway, t.id AS routing_id, t.src AS source_table,
       COALESCE(t.oneway, false) AS oneway, COALESCE(t.kfz_oneway, false) AS kfz_oneway, COALESCE(td.rev, false) AS rev,
       t.id IS NOT NULL AND NOT (c.car_road AND coalesce(w.tags->>'bicycle', '') IN ('no', 'use_sidepath')) AS bike,
       CASE WHEN t.src = 'roads' OR (t.src = 'bikelanes' AND c.car_road) THEN 'R'
            WHEN t.src IS NOT NULL THEN 'S' WHEN c.car_road THEN 'D' ELSE 'C' END AS netz
FROM bikegraph.osm_ways w
LEFT JOIN LATERAL (SELECT * FROM tilda x WHERE x.osm_id = w.way_id AND x.side = 'self' ORDER BY x.prio, x.id LIMIT 1) t ON true
LEFT JOIN tilda_dir td ON td.id = t.id AND td.side = 'self'
CROSS JOIN LATERAL (SELECT
    w.tags->>'highway' IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link',
                           'tertiary', 'tertiary_link', 'residential', 'unclassified', 'living_street', 'pedestrian', 'road',
                           'service', 'track', 'bus_guideway')
    OR (w.tags->>'highway' = 'construction' AND w.tags->>'construction' IN ('motorway_link', 'primary', 'primary_link', 'secondary',
        'secondary_link', 'tertiary', 'tertiary_link', 'residential', 'unclassified', 'living_street', 'pedestrian', 'road',
        'service', 'track', 'bus_guideway'))
    OR (w.tags ? 'motor_vehicle' AND w.tags->>'motor_vehicle' <> 'no')
    OR (w.tags ? 'vehicle' AND w.tags->>'vehicle' <> 'no' AND coalesce(w.tags->>'motor_vehicle', '') <> 'no')
    OR (w.tags ? 'emergency' AND w.tags->>'emergency' <> 'no') AS car_road) c;

CREATE TABLE bikegraph.edges AS
SELECT row_number() OVER (ORDER BY s.way_id, s.seg) AS id, s.way_id, s.seg::int AS seg, s.source, s.target,
       CASE c.netz WHEN 'R' THEN 'fahrbahn' WHEN 'D' THEN 'fahrbahn' WHEN 'S' THEN 'separat' ELSE 'verbindung' END AS herkunft,
       c.netz, c.highway, c.routing_id,
       -- Radverkehr: nur TILDA-Wege; oneway gilt in Richtung der TILDA-Geometrie (rev: gegen die Knotenreihenfolge)
       c.routing_id IS NOT NULL AND c.bike AND (NOT c.oneway OR NOT c.rev) AS fwd,
       c.routing_id IS NOT NULL AND c.bike AND (NOT c.oneway OR c.rev) AS bwd,
       -- Richtungen des Wegs selbst, unabhängig vom Radzugang (routing oneway: darf ein Rad gegen die Linie fahren?)
       NOT c.oneway OR NOT c.rev AS way_fwd,
       NOT c.oneway OR c.rev AS way_bwd,
       NOT c.kfz_oneway OR NOT c.rev AS kfz_fwd,
       NOT c.kfz_oneway OR c.rev AS kfz_bwd,
       ST_Length(s.geom) AS len, s.geom::geometry(LineString, 25833) AS geom
FROM segs s JOIN way_class c ON c.way_id = s.way_id
WHERE ST_Length(s.geom) > 0;
ALTER TABLE bikegraph.edges ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.edges (way_id, seg);
CREATE INDEX ON bikegraph.edges (source);
CREATE INDEX ON bikegraph.edges (target);
CREATE INDEX ON bikegraph.edges (herkunft);
CREATE INDEX ON bikegraph.edges USING gist (geom);

-- Seitenobjekte: gleiche Knoten wie der Elternweg; oneway gilt in ihrer Geometrierichtung (links meist umgedreht)
CREATE TABLE bikegraph.side_objects AS
SELECT t.id AS routing_id, t.osm_id AS way_id, t.side,
       NOT t.oneway OR NOT COALESCE(td.rev, false) AS fwd,
       NOT t.oneway OR COALESCE(td.rev, false) AS bwd,
       t.tags->>'category' AS category
FROM tilda t LEFT JOIN tilda_dir td ON td.id = t.id AND td.side = t.side
WHERE t.src = 'bikelanes' AND t.side IN ('left', 'right');
CREATE INDEX ON bikegraph.side_objects (way_id);
COMMIT;
ANALYZE bikegraph.edges;

\echo 'Kanten nach Herkunft'
SELECT herkunft, count(*) AS kanten, count(DISTINCT way_id) AS wege, round(sum(len)::numeric / 1000) AS km,
       count(*) FILTER (WHERE fwd OR bwd) AS mit_radverkehr FROM bikegraph.edges GROUP BY 1 ORDER BY 1;
\echo 'Seitenobjekte'
SELECT side, count(*), count(*) FILTER (WHERE fwd AND bwd) AS zweirichtung,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bikegraph.edges e WHERE e.way_id = s.way_id AND e.herkunft = 'fahrbahn')) AS ohne_fahrbahn
FROM bikegraph.side_objects s GROUP BY 1;
