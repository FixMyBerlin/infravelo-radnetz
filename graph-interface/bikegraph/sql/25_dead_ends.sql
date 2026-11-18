-- Prüfung zu Schritt 2: tote Enden separater Wege im Gesamtgraphen, nach Abstand zur nächsten Fahrbahn.
-- Vergleichswert (nur TILDA-Routing ohne einfache Gehwege, ganz Berlin): 54.357 tote Enden 2–10 m neben einer Fahrbahn.
CREATE TEMP TABLE deg AS
SELECT v, count(*) AS n FROM (SELECT source AS v FROM bikegraph.edges UNION ALL SELECT target FROM bikegraph.edges) x GROUP BY v;
CREATE INDEX ON deg (v);

CREATE TEMP TABLE way_ends AS
SELECT DISTINCT ON (e.way_id, x.end_no) e.way_id, x.end_no, x.v, x.p
FROM bikegraph.edges e,
     LATERAL (VALUES (1, e.source, ST_StartPoint(e.geom), e.seg), (2, e.target, ST_EndPoint(e.geom), -e.seg)) x(end_no, v, p, ord)
WHERE e.herkunft = 'separat'
ORDER BY e.way_id, x.end_no, x.ord;

SELECT CASE WHEN d IS NULL THEN 'f keine Fahrbahn in 100 m' WHEN d < 2 THEN 'a < 2 m' WHEN d < 10 THEN 'b 2-10 m'
            WHEN d < 20 THEN 'c 10-20 m' ELSE 'd > 20 m' END AS abstand,
       count(*) AS tote_enden
FROM (
    SELECT w.*, (SELECT ST_Distance(f.geom, w.p) FROM bikegraph.edges f
                 WHERE f.herkunft = 'fahrbahn' AND f.geom && ST_Expand(w.p, 100) ORDER BY f.geom <-> w.p LIMIT 1) AS d
    FROM way_ends w JOIN deg ON deg.v = w.v WHERE deg.n = 1
) t GROUP BY 1 ORDER BY 1;
