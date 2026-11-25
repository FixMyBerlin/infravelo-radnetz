-- Routing der RVN-Abschnitte (abschnitte.sh), Abbrüche: wo bricht der durchgehende Weg ab, und was liegt dort.
-- Je Abschnitt, über den eine Route in Teil 2 keinen durchgehenden Weg fand (aus Teilrouten zusammengesetzt, teilroute), eine
-- solche Route (bevorzugt eine, die auf ihm beginnt): der vom Start aus erreichbare Knoten, der
-- entlang der Linie am weitesten liegt (nur Faktoren, ohne Fortschrittskosten), und im Umkreis 40 m die Ursache: entfernte
-- Kanten (Baustelle, Treppen u. ä.), gesperrte Straßen, Einbahn, sonst Netzlücke. Grob: es zählt alles im Umkreis.
-- Ausgang: routing_abschnitte.luecke
DROP TABLE IF EXISTS routing_abschnitte.luecke;
CREATE TABLE routing_abschnitte.luecke (abschnitt int, rid int, lage_m float8, len float8, node bigint);
-- je Abschnitt eine Route ohne durchgehenden Weg, die auf ihm beginnt (sonst eine, die auf ihm endet)
CREATE TEMP TABLE probe AS
SELECT DISTINCT ON (a.abschnitt) a.abschnitt, r.rid
FROM routing_abschnitte.abschnitte a JOIN routing_abschnitte.routen r ON a.abschnitt IN (r.x, r.y)
WHERE EXISTS (SELECT 1 FROM routing_abschnitte.teilroute t WHERE t.rid = r.rid)
ORDER BY a.abschnitt, (r.x = a.abschnitt) DESC, r.rid;
SELECT format($a$INSERT INTO routing_abschnitte.luecke
  SELECT %1$s, %2$s, ST_LineLocatePoint(r.linie, k.geom) * ST_Length(r.linie), ST_Length(r.linie), k.id
  FROM pgr_drivingDistance(%3$L, -1, 1e9, true) d JOIN routing_graph.knoten k ON k.id = d.node, routing_abschnitte.routen r
  WHERE r.rid = %2$s ORDER BY 3 DESC LIMIT 1$a$, p.abschnitt, p.rid,
  format($q$SELECT g.id, g.source, g.target, CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len END AS cost, CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len END AS reverse_cost
     FROM routing_graph.g g, routing_abschnitte.routen r WHERE r.rid = %1$s AND ST_CoveredBy(g.geom, r.korridor)
     UNION ALL SELECT id, source, target, cost, -1 FROM routing_abschnitte.virt WHERE rid = %1$s$q$, p.rid))
FROM probe p ORDER BY p.abschnitt \gexec
ALTER TABLE routing_abschnitte.luecke ADD COLUMN geom geometry(Point, 25833), ADD COLUMN ursache text;
UPDATE routing_abschnitte.luecke l SET geom = k.geom FROM routing_graph.knoten k WHERE k.id = l.node;
-- Ursache im Umkreis 40 m um den Abbruchpunkt: entfernte Kanten (Baustelle, Treppen u. ä.), gesperrte Straßen, Einbahn
UPDATE routing_abschnitte.luecke l SET ursache = x.u FROM (
  SELECT l2.abschnitt, coalesce(
    (SELECT 'entfernt: ' || string_agg(DISTINCT e.highway, ', ') FROM bikegraph.edges e
      WHERE ST_DWithin(e.geom, l2.geom, 40) AND e.highway IN ('construction', 'steps', 'proposed', 'elevator', 'corridor', 'platform')),
    (SELECT 'gesperrte Straße: ' || string_agg(DISTINCT g.highway, ', ') FROM routing_graph.g g
      WHERE ST_DWithin(g.geom, l2.geom, 40) AND g.faktor0 IS NULL AND g.faktor1 IS NULL),
    (SELECT 'Einbahn: ' || string_agg(DISTINCT g.highway, ', ') FROM routing_graph.g g
      WHERE ST_DWithin(g.geom, l2.geom, 40) AND (g.faktor0 IS NULL) <> (g.faktor1 IS NULL)),
    'Netzlücke') AS u
  FROM routing_abschnitte.luecke l2) x
WHERE x.abschnitt = l.abschnitt;
\echo 'Abbruch: Ursache im Umkreis 40 m'
SELECT split_part(ursache, ':', 1) AS art, count(*) AS abschnitte, round(sum(len)::numeric / 1000, 1) AS km_routen FROM routing_abschnitte.luecke GROUP BY 1 ORDER BY 2 DESC;
SELECT ursache, count(*) FROM routing_abschnitte.luecke GROUP BY 1 ORDER BY 2 DESC LIMIT 12;
\echo 'Abbruch nach wie vielen Metern (Anteil der Route)'
SELECT width_bucket(lage_m / nullif(len, 0), 0, 1, 4) AS viertel, count(*) FROM routing_abschnitte.luecke GROUP BY 1 ORDER BY 1;
