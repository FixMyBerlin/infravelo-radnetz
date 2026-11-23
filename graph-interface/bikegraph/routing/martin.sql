-- Martin-Ebenen des Routing-Matchers (routing_qa.sh nach abschnitte.sh und luecken.sql), Schema routing_martin. Eigene Tabellen mit id und
-- festem Geometrietyp (Martin), unabhängig von routing_abschnitte, das jeder Lauf neu baut.
--   routing_rvn_diff   unsere Änderungen am RVN (matching_korr.korrektur): entfernte Kanten (Geometrie aus dem
--                      ursprünglichen RVN, matching_orig), gelöste und neue Kanten (Geometrie aus dem korrigierten RVN)
--   routing_radwege    Kanten des Routing-Graphen mit Radinfrastruktur (Stufe 1 in einer Richtung: Radwege, Rad- und
--                      Schutzstreifen, Busspuren, Fahrradstraßen, Kreuzungswege, [TODO])
--   routing_wege       die übrigen Wegeklassen (footway, path, pedestrian, steps, track, bridleway, elevator, corridor,
--                      cycleway ohne Objekt)
--   routing_strassen   die übrige Straßentopologie (Fahrbahnen, Erschließungsstraßen, Baustellen)
--                      Graph-Ebenen mit Richtung (beide, vorwärts, rückwärts, gesperrt) und Zusatzkante (treppe,
--                      service, baustelle: nur als letzte Option, faktor_plus)
--   routing_routen     die Routen: Vereinigung aller Wege je Kante des Graphen und Richtung, mit Führungsform, Objekt,
--                      Zahl der Routen (ganze Routen, ohne Schnitt in Mitte und Kreuzung)
--   routing_crossings  Fahrten durch die RVN-Kreuzungen: je Route x -> y das Stück zwischen der Teilung von x und der
--                      Vereinigung von y (sonst Durchfahrt), mit RVN-Knoten und Führungsform; lang = länger als der
--                      Mittelwert aller Kreuzungsstücke (mittel_m, faktor, rang 1 = längstes)
--   routing_unbequem   unbequeme Verbindungen: von Routen benutzte Zusatzkanten (Treppen, Erschließungsstraßen,
--                      Baustellen) je Kante mit Zahl der Routen, und Brücken über Netzlücken
--   routing_rvn        Ergebnis je RVN-Kante und Richtung: Führungsform aus dem Routing, v7, Baseline (Henri), Status
--                      (gleich = wie v7, anders, ohne = kein Ergebnis), Abdeckung
--   routing_diff_v7    RVN-Kanten je Richtung, deren Führungsform vom Routing anders ist als v7 (oder ohne Ergebnis), mit Klasse
--   routing_urteil_routing, routing_urteil_v7, routing_urteil_grenzfall  die Unterschiede zu v7 mit Urteil aus den Belegen
--                      vor Ort (martin_beurteilung.sql): Routing richtig, v7 richtig, Grenzfall / TILDA-Daten / ohne v7
--   routing_haltestellen  Bushaltestellen mit nächster RVN-Kante und Streifen-Formen bis 20 m
--   routing_luecken    Abbrüche: Abschnitte ohne durchgehenden Weg mit Abbruchpunkt und grober Ursache
-- routing_routen und routing_crossings zeigen die versetzte Geometrie (geom_versetzt aus abschnitte_5_versatz.sql):
-- Radstreifen auf ihrer Seite statt auf der Straßenmittellinie.
DROP SCHEMA IF EXISTS routing_martin CASCADE;
CREATE SCHEMA routing_martin;

-- Änderungen am RVN (nur nach der wahlweisen Korrektur rvn_korrektur.sh, sonst leer)
CREATE TABLE routing_martin.routing_rvn_diff (id int, element_nr text, art text, beschreibung text, element_darunter text,
    strassenname text, laenge_m numeric, geom geometry(MultiLineString, 25833));
SELECT to_regclass('matching_korr.korrektur') IS NOT NULL AND to_regclass('matching_orig.reference_edges') IS NOT NULL AS mit_korrektur \gset
\if :mit_korrektur
INSERT INTO routing_martin.routing_rvn_diff
SELECT row_number() OVER (ORDER BY k.art, k.element_nr)::int AS id, k.element_nr, k.art, k.beschreibung, k.element_darunter,
       coalesce(n.strassenname, o.strassenname)::text AS strassenname, round(ST_Length(coalesce(n.geom, o.geom))::numeric) AS laenge_m,
       ST_Multi(coalesce(n.geom, o.geom))::geometry(MultiLineString, 25833) AS geom
FROM matching_korr.korrektur k
LEFT JOIN (SELECT element_nr, max(strassenname) AS strassenname, ST_Collect(geom) AS geom FROM matching_orig.reference_edges GROUP BY 1) o
       ON o.element_nr = k.element_nr
LEFT JOIN (SELECT element_nr, max(strassenname) AS strassenname, ST_Collect(geom) AS geom FROM matching.reference_edges GROUP BY 1) n
       ON n.element_nr = k.element_nr AND k.art <> 'entfernt';
\endif

-- Routing-Graph in drei Klassen
CREATE TEMP TABLE graph AS
SELECT g.id, g.highway, g.herkunft, g.routing_id, g.fuehr0, g.fuehr1, g.faktor0, g.faktor1, g.zusatz, g.faktor_plus::numeric AS faktor_plus,
       round(g.len::numeric, 1) AS len,
       CASE WHEN g.faktor0 IS NULL AND g.faktor1 IS NULL THEN 'gesperrt' WHEN g.faktor1 IS NULL THEN 'vorwärts'
            WHEN g.faktor0 IS NULL THEN 'rückwärts' ELSE 'beide' END AS richtung,
       CASE WHEN f.rad THEN 'rad'
            WHEN g.highway IN ('footway', 'path', 'pedestrian', 'steps', 'track', 'bridleway', 'elevator', 'corridor', 'cycleway') THEN 'weg'
            ELSE 'strasse' END AS klasse,
       g.geom::geometry(LineString, 25833) AS geom
FROM routing_graph.g g
CROSS JOIN LATERAL (SELECT bool_or(x IN ('Radfahrstreifen', 'Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)',
                       'Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)', 'Geschützter Radfahrstreifen', 'Schutzstreifen',
                       'Fahrradstraße /-zone (Z 244)', 'Radweg', 'Gemeinsamer Geh- und Radweg mit Z240',
                       'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)', 'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)',
                       'Kreuzungsweg', '[TODO] Klärung notwendig')) AS rad
                    FROM (VALUES (g.fuehr0), (g.fuehr1)) v(x)) f;
CREATE TABLE routing_martin.routing_radwege AS
SELECT id, highway, herkunft, routing_id, fuehr0, fuehr1, faktor0, faktor1, richtung, len, geom FROM graph WHERE klasse = 'rad';
CREATE TABLE routing_martin.routing_wege AS
SELECT id, highway, herkunft, routing_id, fuehr0, fuehr1, faktor0, faktor1, richtung, zusatz, faktor_plus, len, geom FROM graph WHERE klasse = 'weg';
CREATE TABLE routing_martin.routing_strassen AS
SELECT id, highway, herkunft, routing_id, fuehr0, fuehr1, faktor0, faktor1, richtung, zusatz, faktor_plus, len, geom FROM graph WHERE klasse = 'strasse';

-- Routen: Vereinigung aller Wege je Kante des Graphen und Richtung (ganze Routen, ohne Schnitt in Mitte und Kreuzung),
-- mit Führungsform, Objekt, Zahl der Routen; Geometrie versetzt wie in Teil 5 (pfad_versatz)
CREATE TABLE routing_martin.routing_routen AS
SELECT row_number() OVER (ORDER BY g.id, x.ri)::int AS id, g.id AS kante, x.ri, g.routing_id,
       CASE WHEN x.ri = 0 THEN g.objekt0 ELSE g.objekt1 END AS objekt,
       coalesce(CASE WHEN x.ri = 0 THEN g.fuehr0 ELSE g.fuehr1 END, 'Keine Radinfrastruktur vorhanden') AS fuehr,
       CASE WHEN x.ri = 0 THEN g.faktor0 ELSE g.faktor1 END AS faktor, x.routen, x.rids, x.geom::geometry(LineString, 25833) AS geom
FROM (SELECT p.edge, CASE WHEN p.node = g.source THEN 0 ELSE 1 END AS ri, count(DISTINCT p.rid)::int AS routen,
             string_agg(DISTINCT p.rid::text, ', ') AS rids,
             (array_agg(coalesce(v.geom, CASE WHEN p.node = g.source THEN g.geom ELSE ST_Reverse(g.geom) END)))[1] AS geom
      FROM routing_abschnitte.pfad p JOIN routing_graph.g g ON g.id = p.edge
      LEFT JOIN routing_abschnitte.pfad_versatz v ON v.rid = p.rid AND v.seq = p.seq
      WHERE p.edge >= 0 GROUP BY 1, 2) x
JOIN routing_graph.g g ON g.id = x.edge;

-- Kreuzungsstücke mit Länge im Vergleich zum Mittelwert
CREATE TABLE routing_martin.routing_crossings AS
SELECT k.rid AS id, k.knoten, k.x AS abschnitt_von, k.y AS abschnitt_nach, k.kanten::int, k.m, k.fuehr, k.fuehr_alle, k.von_gabelung, k.bis_gabelung,
       k.zusatz, k.zusatz_m, k.unbequem, k.m > a.mittel AS lang, round(a.mittel, 1) AS mittel_m, round(k.m / nullif(a.mittel, 0), 2) AS faktor,
       (rank() OVER (ORDER BY k.m DESC))::int AS rang, k.geom_versetzt::geometry(MultiLineString, 25833) AS geom
FROM routing_abschnitte.kreuzung_route k, (SELECT avg(m) AS mittel FROM routing_abschnitte.kreuzung_route) a;

-- Unbequeme Verbindungen: benutzte Zusatzkanten je Kante und Brücken über Netzlücken
CREATE TABLE routing_martin.routing_unbequem AS
SELECT row_number() OVER (ORDER BY art, kante, rid)::int AS id, * FROM (
    SELECT g.zusatz AS art, g.id AS kante, NULL::int AS rid, count(DISTINCT p.rid)::int AS routen,
           string_agg(DISTINCT p.rid::text, ', ') AS rids, round(g.len::numeric, 1) AS m, g.highway, g.geom::geometry(LineString, 25833) AS geom
    FROM routing_abschnitte.pfad p JOIN routing_graph.g g ON g.id = p.edge WHERE p.edge >= 0 AND g.zusatz IS NOT NULL
    GROUP BY g.id, g.zusatz, g.len, g.highway, g.geom
    UNION ALL
    SELECT 'brücke', NULL, b.rid, 1, b.rid::text, round(b.laenge::numeric, 1), NULL, b.geom::geometry(LineString, 25833)
    FROM routing_abschnitte.bruecke b) x;

-- Ergebnis je RVN-Kante und Unterschiede zu v7
-- Vergleichsdaten (routing_qa.sh lädt sie): Datensatz C von v7 (bikegraph.c_v7) und die Baseline (bikegraph.c_base,
-- Spalte henri); fehlt eine Tabelle, bleiben ihre Spalten leer
SELECT to_regclass('bikegraph.c_v7') IS NOT NULL AS mit_v7, to_regclass('bikegraph.c_base') IS NOT NULL AS mit_base \gset
\if :mit_v7
CREATE TEMP VIEW qa_v7 AS SELECT element_nr::text, ri::int, fuehr::text FROM bikegraph.c_v7;
\else
CREATE TEMP TABLE qa_v7 (element_nr text, ri int, fuehr text);
\endif
\if :mit_base
CREATE TEMP VIEW qa_base AS SELECT element_nr::text, ri::int, fuehr::text FROM bikegraph.c_base;
\else
CREATE TEMP TABLE qa_base (element_nr text, ri int, fuehr text);
\endif
CREATE TABLE routing_martin.routing_rvn AS
SELECT row_number() OVER (ORDER BY e.rvn_id, e.ri)::int AS id, e.rvn_id, e.element_nr, e.ri, e.abschnitt,
       e.fuehr AS routing, c.fuehr AS v7, h.fuehr AS henri,
       CASE WHEN e.fuehr IS NULL THEN 'ohne' WHEN e.fuehr = c.fuehr THEN 'gleich' ELSE 'anders' END AS status, e.rueckfall, e.zusatz, e.zusatz_m, e.unbequem,
       e.m, e.m_gesamt, e.abdeckung, e.fuehr_weg, e.kandidat, e.kandidat_mehr, r.geom::geometry(LineString, 25833) AS geom
FROM routing_abschnitte.ergebnis e JOIN matching.reference_edges r ON r.id = e.rvn_id
LEFT JOIN qa_v7 c ON c.element_nr = e.element_nr AND c.ri = e.ri
LEFT JOIN qa_base h ON h.element_nr = e.element_nr AND h.ri = e.ri;
-- Rückfall (kein Stück aus dem Routing, Keine Radinfrastruktur), anders als v7 bei v7 = Henri, anders als v7 bei v7 <> Henri
CREATE TABLE routing_martin.routing_diff_v7 AS
SELECT id, rvn_id, element_nr, ri, abschnitt, routing, v7, henri,
       CASE WHEN rueckfall THEN 'Rückfall (keine Radinfra)' WHEN v7 IS NOT DISTINCT FROM henri THEN 'anders, v7 = Henri' ELSE 'anders, v7 ≠ Henri' END AS klasse,
       routing IS NOT DISTINCT FROM henri AS routing_gleich_henri, abdeckung, geom
FROM routing_martin.routing_rvn WHERE routing IS DISTINCT FROM v7;
-- Beurteilung der Unterschiede zu v7 (Routing richtig, v7 richtig, Grenzfall)
\ir martin_beurteilung.sql

-- Abbrüche: Abschnitte ohne durchgehenden Weg mit Abbruchpunkt und grober Ursache (luecken.sql); ohne die Tabelle leer
CREATE TABLE routing_martin.routing_luecken (id int, abschnitt int, rid int, ursache text, lage_m numeric, len numeric, geom geometry(Point, 25833));
SELECT to_regclass('routing_abschnitte.luecke') IS NOT NULL AS mit_luecke \gset
\if :mit_luecke
INSERT INTO routing_martin.routing_luecken
SELECT row_number() OVER (ORDER BY abschnitt)::int, abschnitt, rid, ursache, round(lage_m::numeric), round(len::numeric), geom::geometry(Point, 25833)
FROM routing_abschnitte.luecke WHERE geom IS NOT NULL;
\endif

-- Bushaltestellen (bikegraph.bus_stops, siehe graph.sql) mit nächster RVN-Kante und den Streifen-Formen im Graphen bis 20 m
-- (Radfahrstreifen/Schutzstreifen, nach der Umwandlung an Haltestellen); ohne die Tabelle leer
CREATE TABLE routing_martin.routing_haltestellen (id int, name text, osm_id text, route_ref text, bus_bay text, shelter text,
    rvn_id int, abstand_rvn_m numeric, streifen_20m text, geom geometry(Point, 25833));
SELECT to_regclass('bikegraph.bus_stops') IS NOT NULL AS mit_halt \gset
\if :mit_halt
INSERT INTO routing_martin.routing_haltestellen
SELECT b.ogc_fid, b.name, b."@id", b.route_ref, b.bus_bay, b.shelter, n.id, round(n.d::numeric, 1),
       (SELECT string_agg(DISTINCT f, ', ') FROM routing_graph.g g, LATERAL (VALUES (g.fuehr0), (g.fuehr1)) x(f)
        WHERE ST_DWithin(g.geom, b.geom, 20) AND f IN ('Radfahrstreifen', 'Schutzstreifen')),
       b.geom::geometry(Point, 25833)
FROM bikegraph.bus_stops b
LEFT JOIN LATERAL (SELECT r.id, ST_Distance(r.geom, b.geom) AS d FROM matching.reference_edges r ORDER BY r.geom <-> b.geom LIMIT 1) n ON true;
\endif

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['routing_rvn_diff', 'routing_radwege', 'routing_wege', 'routing_strassen', 'routing_routen', 'routing_crossings',
                             'routing_unbequem', 'routing_rvn', 'routing_diff_v7', 'routing_urteil_routing', 'routing_urteil_v7',
                             'routing_urteil_grenzfall', 'routing_haltestellen', 'routing_luecken'] LOOP
        EXECUTE format('ALTER TABLE routing_martin.%I ADD PRIMARY KEY (id)', t);
        EXECUTE format('CREATE INDEX ON routing_martin.%I USING gist (geom)', t);
        EXECUTE format('ANALYZE routing_martin.%I', t);
    END LOOP;
END $$;
\echo 'Martin-Ebenen (Zeilen)'
SELECT 'routing_rvn_diff' AS ebene, count(*) FROM routing_martin.routing_rvn_diff
UNION ALL SELECT 'routing_radwege', count(*) FROM routing_martin.routing_radwege
UNION ALL SELECT 'routing_wege', count(*) FROM routing_martin.routing_wege
UNION ALL SELECT 'routing_strassen', count(*) FROM routing_martin.routing_strassen
UNION ALL SELECT 'routing_routen', count(*) FROM routing_martin.routing_routen
UNION ALL SELECT 'routing_crossings', count(*) FROM routing_martin.routing_crossings
UNION ALL SELECT 'routing_unbequem', count(*) FROM routing_martin.routing_unbequem
UNION ALL SELECT 'routing_rvn', count(*) FROM routing_martin.routing_rvn
UNION ALL SELECT 'routing_diff_v7', count(*) FROM routing_martin.routing_diff_v7
UNION ALL SELECT 'routing_urteil_routing', count(*) FROM routing_martin.routing_urteil_routing
UNION ALL SELECT 'routing_urteil_v7', count(*) FROM routing_martin.routing_urteil_v7
UNION ALL SELECT 'routing_urteil_grenzfall', count(*) FROM routing_martin.routing_urteil_grenzfall
UNION ALL SELECT 'routing_haltestellen', count(*) FROM routing_martin.routing_haltestellen
UNION ALL SELECT 'routing_luecken', count(*) FROM routing_martin.routing_luecken;
