-- Routing der RVN-Abschnitte, Teil 2 (abschnitte.sh): kürzeste Wege für jede :teile-te Route (rid modulo :teile = :teil);
-- mehrere Teile laufen parallel in eigenen Verbindungen. Eingang und Ausgang im Schema :schema (Teil 1: routen, virt,
-- korridor_kanten, kanten_sql, abschnitt_kanten; Ausgang: pfad, teilroute, bruecke).
-- 1. Kürzester Weg je Route x -> y (zwei Kreuzungen).
-- 2. Routen ohne Weg in Teilrouten: je RVN-Kante von x und y (in Fahrtrichtung) ein eigener kürzester Weg im Korridor der
--    Route, mit Start- und Zielmenge an den Enden der RVN-Kante (wie in Teil 1). So bekommen die RVN-Kanten bis zur Lücke
--    und ab ihr ihre Wege, auch wenn die ganze Route nicht durchkommt.
-- 3. Brücken nur für Teilrouten ohne Weg (Erklärung in Teil 1 bei der Tabelle bruecke).
-- 4. Die Teilrouten in Fahrtrichtung aneinandergehängt als Weg der Route (pfad); zwischen zwei Teilrouten verbindet die
--    virtuelle Zielkante der vorigen (edge < 0, zählt nicht) mit dem Start der nächsten.
-- Mit -v zweitlauf=true (Standard false) als letzte Option über die Zusatzkanten (Treppen/Aufzüge, Erschließungsstraßen,
-- Baustellen; graph.sql, faktor_plus), je Schritt nur für das, was noch keinen Weg hat:
--   1b ganze Route mit Zusatzkanten, wenn Schritt 1 keinen Weg findet
--   2b Teilroute mit Zusatzkanten, wenn Schritt 2 keinen Weg findet
--   3  Brücken nur für Teilrouten, die auch so keinen Weg haben, gesucht auf dem Graphen mit Zusatzkanten
-- Protokoll je Route mit Metern auf Zusatzkanten im endgültigen Weg in zweitlauf; Teil 3 kennzeichnet sie (unbequem).
-- Mit -v kette=true (Standard true; -v kette=false für unabhängige Teilrouten je RVN-Kante) ersetzt abschnitte_2_kette.sql
-- die Schritte 2 bis 4: ein zusammenhängender Weg
-- Stück für Stück, Brücken genau an der Lücke, Stücke mit leerer Zielmenge übersprungen (ohne die Ersatzmengen unten).
-- psql-Variablen: schema, teil, teile, brueck_m, brueck_faktor, fang_m, korridor_m, anschluss_faktor, quer_faktor
-- (Standardwerte wie in Teil 1), kette (Standard true), kette_m (Standard 300), zweitlauf (Standard false)
\if :{?schema} \else \set schema routing_abschnitte \endif
\if :{?teil} \else \set teil 0 \endif
\if :{?teile} \else \set teile 1 \endif
\if :{?brueck_m} \else \set brueck_m 50 \endif
\if :{?brueck_faktor} \else \set brueck_faktor 10 \endif
\if :{?fang_m} \else \set fang_m 50 \endif
\if :{?korridor_m} \else \set korridor_m 50 \endif
\if :{?anschluss_faktor} \else \set anschluss_faktor 2.0 \endif
\if :{?quer_faktor} \else \set quer_faktor 0.2 \endif
\if :{?kette} \else \set kette true \endif
\if :{?zweitlauf} \else \set zweitlauf false \endif
SET search_path TO :"schema", public;

-- 1. kürzeste Wege, eine Anweisung je Route
SELECT format($a$INSERT INTO pfad SELECT %s, d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d$a$, k.rid, k.q)
FROM kanten_sql k WHERE k.rid % :teile = :teil ORDER BY k.rid \gexec
\if :zweitlauf
-- 1b. ganze Route mit Zusatzkanten für die Routen ohne Weg
SELECT format($a$INSERT INTO pfad SELECT %1$s, d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(
  $q$SELECT g.id, g.source, g.target,
                 CASE WHEN coalesce(g.faktor0, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor0, g.faktor_plus) + k.zusatz_je_m) END AS cost,
                 CASE WHEN coalesce(g.faktor1, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor1, g.faktor_plus) + k.zusatz_je_m) END AS reverse_cost
     FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
     UNION ALL SELECT id, source, target, cost, -1 FROM virt WHERE rid = %1$s$q$, -1::bigint, -2::bigint, true) d$a$, k.rid)
FROM kanten_sql k LEFT JOIN (SELECT DISTINCT rid FROM pfad WHERE rid % :teile = :teil) p ON p.rid = k.rid
WHERE k.rid % :teile = :teil AND p.rid IS NULL ORDER BY k.rid \gexec
\endif

-- 2. Teilrouten je RVN-Kante für die Routen dieses Teils ohne Weg
CREATE TEMP TABLE ohne_weg AS
SELECT k.rid FROM kanten_sql k LEFT JOIN (SELECT DISTINCT rid FROM pfad WHERE rid % :teile = :teil) p ON p.rid = k.rid
WHERE k.rid % :teile = :teil AND p.rid IS NULL;
CREATE TEMP TABLE teilstueck AS
SELECT o.rid, row_number() OVER (PARTITION BY o.rid ORDER BY CASE WHEN ak.abschnitt = r.x THEN 0 ELSE 1 END, ak.pos)::int AS t,
       ak.rvn_id, ak.ri, ak.geom
FROM ohne_weg o JOIN routen r ON r.rid = o.rid JOIN abschnitt_kanten ak ON ak.abschnitt = r.x OR ak.abschnitt = r.y;
CREATE INDEX ON teilstueck (rid, t);
-- Start- und Zielmenge je Teilroute an den Enden ihrer RVN-Kante (Kosten wie in Teil 1)
CREATE TEMP TABLE teil_virt AS
SELECT t.rid, t.t, -(row_number() OVER ())::bigint AS id, -1::bigint AS source, k.id AS target,
       ST_LineLocatePoint(t.geom, k.geom) * ST_Length(t.geom) * :anschluss_faktor + ST_Distance(k.geom, t.geom) * :quer_faktor AS cost
FROM teilstueck t JOIN routing_graph.knoten k ON ST_DWithin(k.geom, ST_StartPoint(t.geom), :fang_m) AND ST_DWithin(k.geom, t.geom, :korridor_m)
WHERE ST_Distance(k.geom, ST_StartPoint(t.geom)) < ST_Distance(k.geom, ST_EndPoint(t.geom))
UNION ALL
SELECT t.rid, t.t, -(10000000 + row_number() OVER ())::bigint, k.id, -2,
       (1 - ST_LineLocatePoint(t.geom, k.geom)) * ST_Length(t.geom) * :anschluss_faktor + ST_Distance(k.geom, t.geom) * :quer_faktor
FROM teilstueck t JOIN routing_graph.knoten k ON ST_DWithin(k.geom, ST_EndPoint(t.geom), :fang_m) AND ST_DWithin(k.geom, t.geom, :korridor_m)
WHERE ST_Distance(k.geom, ST_EndPoint(t.geom)) <= ST_Distance(k.geom, ST_StartPoint(t.geom));
-- Leere Start- oder Zielmenge (kein Knoten im Fang am Kantenende, das Netz endet davor): stattdessen alle Korridorknoten
-- der nahen Kantenhälfte, mit denselben Kosten (sie bevorzugen den Knoten nächst dem Ende). Nicht in der Kette: dort
-- entfällt das Stück, das nächste deckt die Kante mit ab.
\if :kette \else
INSERT INTO teil_virt
SELECT t.rid, t.t, -(20000000 + row_number() OVER ())::bigint, -1, k.id,
       ST_LineLocatePoint(t.geom, k.geom) * ST_Length(t.geom) * :anschluss_faktor + ST_Distance(k.geom, t.geom) * :quer_faktor
FROM teilstueck t JOIN routing_graph.knoten k ON ST_DWithin(k.geom, t.geom, :korridor_m)
LEFT JOIN (SELECT DISTINCT rid, t FROM teil_virt WHERE source = -1) s ON s.rid = t.rid AND s.t = t.t
WHERE s.rid IS NULL AND ST_Distance(k.geom, ST_StartPoint(t.geom)) < ST_Distance(k.geom, ST_EndPoint(t.geom));
INSERT INTO teil_virt
SELECT t.rid, t.t, -(30000000 + row_number() OVER ())::bigint, k.id, -2,
       (1 - ST_LineLocatePoint(t.geom, k.geom)) * ST_Length(t.geom) * :anschluss_faktor + ST_Distance(k.geom, t.geom) * :quer_faktor
FROM teilstueck t JOIN routing_graph.knoten k ON ST_DWithin(k.geom, t.geom, :korridor_m)
LEFT JOIN (SELECT DISTINCT rid, t FROM teil_virt WHERE target = -2) s ON s.rid = t.rid AND s.t = t.t
WHERE s.rid IS NULL AND ST_Distance(k.geom, ST_EndPoint(t.geom)) <= ST_Distance(k.geom, ST_StartPoint(t.geom));
\endif
CREATE INDEX ON teil_virt (rid, t);
ANALYZE teil_virt;
\if :kette
\ir abschnitte_2_kette.sql
\else
CREATE TEMP TABLE teil_sql AS
SELECT t.rid, t.t, format($q$SELECT g.id, g.source, g.target,
                 CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len * (g.faktor0 + k.zusatz_je_m) END AS cost,
                 CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len * (g.faktor1 + k.zusatz_je_m) END AS reverse_cost
               FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
               UNION ALL SELECT id, source, target, cost, -1 FROM teil_virt WHERE rid = %1$s AND t = %2$s$q$, t.rid, t.t) AS q,
       format($q$SELECT g.id, g.source, g.target,
                 CASE WHEN coalesce(g.faktor0, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor0, g.faktor_plus) + k.zusatz_je_m) END AS cost,
                 CASE WHEN coalesce(g.faktor1, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor1, g.faktor_plus) + k.zusatz_je_m) END AS reverse_cost
               FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
               UNION ALL SELECT id, source, target, cost, -1 FROM teil_virt WHERE rid = %1$s AND t = %2$s$q$, t.rid, t.t) AS q_plus
FROM teilstueck t;
CREATE TEMP TABLE teil_pfad (rid int, t int, seq int, node bigint, edge bigint, cost float8, agg_cost float8);
SELECT format($a$INSERT INTO teil_pfad SELECT %s, %s, d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d$a$, s.rid, s.t, s.q)
FROM teil_sql s ORDER BY s.rid, s.t \gexec
\if :zweitlauf
-- 2b. Teilrouten ohne Weg noch einmal mit Zusatzkanten
SELECT format($a$INSERT INTO teil_pfad SELECT %s, %s, d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d$a$, s.rid, s.t, s.q_plus)
FROM teil_sql s LEFT JOIN (SELECT DISTINCT rid, t FROM teil_pfad) p ON p.rid = s.rid AND p.t = s.t WHERE p.rid IS NULL ORDER BY s.rid, s.t \gexec
\endif

-- 3. Brücken für Teilrouten ohne Weg (mit zweitlauf auf dem Graphen mit Zusatzkanten)
CREATE TEMP TABLE teil_ohne AS
SELECT s.rid, s.t, CASE WHEN :zweitlauf THEN s.q_plus ELSE s.q END AS q
FROM teil_sql s LEFT JOIN (SELECT DISTINCT rid, t FROM teil_pfad) p ON p.rid = s.rid AND p.t = s.t WHERE p.rid IS NULL;
SELECT format($a$WITH vor AS (SELECT node, agg_cost FROM pgr_drivingDistance(%3$L, -1, 1e9, true)),
     rueck AS (SELECT node, agg_cost FROM pgr_drivingDistance(%4$L, -2, 1e9, true)),
     paar AS (SELECT v.node AS a, w.node AS b, v.agg_cost AS kv, w.agg_cost AS kr, ST_Distance(ka.geom, kb.geom) AS d, ka.geom AS ga, kb.geom AS gb
              FROM vor v JOIN routing_graph.knoten ka ON ka.id = v.node
              JOIN routing_graph.knoten kb ON ST_DWithin(kb.geom, ka.geom, %5$s) JOIN rueck w ON w.node = kb.id
              ORDER BY v.agg_cost + ST_Distance(ka.geom, kb.geom) * %6$s + w.agg_cost LIMIT 1),
     br AS (INSERT INTO bruecke SELECT %1$s, %2$s, a, b, d, kv, kr, ST_MakeLine(ga, gb) FROM paar RETURNING a, b, laenge),
     p1 AS (SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM paar, pgr_dijkstra(%3$L, -1::bigint, paar.a, true) d),
     p2 AS (SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM paar, pgr_dijkstra(%3$L, paar.b, -2::bigint, true) d),
     n1 AS (SELECT max(seq) AS s, max(agg_cost) AS k FROM p1)
INSERT INTO teil_pfad
SELECT %1$s, %2$s, p1.seq, p1.node, CASE WHEN p1.node = br.a AND p1.edge = -1 THEN -(1000000000 + %1$s * 1000 + %2$s) ELSE p1.edge END,
       CASE WHEN p1.node = br.a AND p1.edge = -1 THEN br.laenge * %6$s ELSE p1.cost END, p1.agg_cost
FROM p1, br
UNION ALL
SELECT %1$s, %2$s, n1.s + p2.seq, p2.node, p2.edge, p2.cost, n1.k + br.laenge * %6$s + p2.agg_cost FROM p2, n1, br$a$,
       o.rid, o.t, o.q, format('SELECT id, target AS source, source AS target, cost, reverse_cost FROM (%s) x', o.q), :brueck_m, :brueck_faktor)
FROM teil_ohne o ORDER BY o.rid, o.t \gexec

-- Auskunft je Teilroute
INSERT INTO teilroute
SELECT t.rid, t.t, t.rvn_id, t.ri, (p.rid IS NOT NULL) AS mit_weg, (b.rid IS NOT NULL) AS mit_bruecke
FROM teilstueck t LEFT JOIN (SELECT DISTINCT rid, t FROM teil_pfad) p ON p.rid = t.rid AND p.t = t.t
LEFT JOIN bruecke b ON b.rid = t.rid AND b.teil = t.t;

-- 4. Teilrouten aneinanderhängen: echte Knoten in Fahrtrichtung; die virtuelle Zielkante einer Teilroute verbindet zum
-- Start der nächsten (endet sie am selben Knoten, entfällt die doppelte Zeile)
INSERT INTO pfad
SELECT rid, row_number() OVER (PARTITION BY rid ORDER BY t, seq)::int, node, edge, cost, agg_cost
FROM (SELECT tp.*, lead(tp.node) OVER (PARTITION BY tp.rid ORDER BY tp.t, tp.seq) AS naechster
      FROM teil_pfad tp WHERE tp.node >= 0) x
WHERE NOT (x.edge < 0 AND x.naechster = x.node);
\endif

-- Protokoll: Routen dieses Teils mit Zusatzkanten im Weg (route: ganze Route über Zusatzkanten, teil: aus Teilrouten)
\if :zweitlauf
INSERT INTO zweitlauf
SELECT p.rid, CASE WHEN t.rid IS NULL THEN 'route' ELSE 'teil' END,
       coalesce(sum(g.len) FILTER (WHERE g.zusatz = 'treppe'), 0), coalesce(sum(g.len) FILTER (WHERE g.zusatz = 'service'), 0),
       coalesce(sum(g.len) FILTER (WHERE g.zusatz = 'baustelle'), 0)
FROM pfad p JOIN routing_graph.g g ON g.id = p.edge AND p.edge >= 0
LEFT JOIN (SELECT DISTINCT rid FROM teilroute WHERE rid % :teile = :teil) t ON t.rid = p.rid
WHERE p.rid % :teile = :teil GROUP BY p.rid, t.rid HAVING count(*) FILTER (WHERE g.zusatz IS NOT NULL) > 0;
\endif
