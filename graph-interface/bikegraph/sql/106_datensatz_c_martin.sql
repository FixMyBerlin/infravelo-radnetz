-- Datensatz C der Baseline und des neuen Laufs sowie ihre Abweichungen für Martin (nach compare_c.sh).
-- Eingang: bikegraph.c_base (Baseline), bikegraph.c_cand (neuer Datensatz C), bikegraph.c_faelle (Urteile je
-- abweichender Kanten-Richtung), alle aus compare_c.sh.
-- Ausgang (Schema datensatz_c):
--   baseline_c  je RVN-Kante und Richtung die Führungsform der Baseline (Geometrie der RVN-Kante)
--   new_c       dasselbe für den neuen Datensatz C
--   diff_c      nur Kanten-Richtungen mit anderer Führungsform (oder nur in einem der beiden): beide Werte, Urteil und
--               Regel aus compare_c.sh, beteiligte TILDA-Objekte; nur Richtungen, die das RVN vorsieht (R- und G-Kanten
--               nur ri 0, wie sql/70)
--   baseline_wins  Teil von diff_c mit Urteil Baseline (Baseline besser)
--   neu_wins       Teil von diff_c mit Urteil Kandidat (neuer Datensatz besser)
--   diff_alle   alle Kanten-Richtungen, in denen irgendein Attribut abweicht (Führungsform eingeschlossen): beide Werte
--               nur für die abweichenden Attribute (übereinstimmende bleiben leer, Martin lässt sie aus den Kacheln weg),
--               abweichend = Liste der Attribute; Breite als Zahl verglichen (2 und 2.0 gleich); dieselben Richtungen
--               wie diff_c
--   wege        Eingang der trace_group wege (bikegraph.dc_input, sql/104): TILDA-Wege, ungefaltete Radwege, ungefaltete
--               Reste; je Stück Art, TILDA-Objekt, Führungsform und Kategorie aus dem Eingang, rvn_m (auf dem RVN
--               gemessene Länge der eigenen, nicht gespiegelten Intervalle aus bikegraph.dc_iv_raw; 0 = nicht gematcht)
--               und rvn (getroffene Kanten mit ri)
--   strassen_traces  je Trace der trace_group strassen (bikegraph.dc_iv_raw_traces, ohne Kontext) eine Linie: Wege in
--               Reihenfolge, Zahl der Wege, Beobachtungen, gematchte Beobachtungen, HMM-Brüche
--   new_b       (datensatz_c.sh, vor dieser Datei) Datensatz B des neuen Laufs
CREATE SCHEMA IF NOT EXISTS datensatz_c;
BEGIN;
DROP TABLE IF EXISTS datensatz_c.baseline_c, datensatz_c.new_c, datensatz_c.diff_c, datensatz_c.baseline_wins, datensatz_c.neu_wins,
    datensatz_c.diff_alle, datensatz_c.wege, datensatz_c.strassen_traces;

-- Intervalle der Wege je Eingangsstück, vorab verdichtet (gematcht_m nur aus nicht gespiegelten Intervallen)
CREATE TEMP TABLE wege_iv ON COMMIT DROP AS
SELECT input_id, sum(to_m - from_m) FILTER (WHERE mirrored = 0) AS gematcht_m,
       string_agg(DISTINCT element_nr || ' ri ' || ri, ', ') AS rvn
FROM bikegraph.dc_iv_raw WHERE trace_group = 'wege' GROUP BY input_id;
CREATE INDEX ON wege_iv (input_id);
-- Führungsform und Kategorie je TILDA-Objekt aus dem Eingang
CREATE TEMP TABLE wege_attr ON COMMIT DROP AS
SELECT DISTINCT ON (input_ref) input_ref, attrs->>'fuehr' AS fuehr, attrs->>'tilda_category' AS kategorie
FROM bikegraph.input_edges ORDER BY input_ref, id;
CREATE INDEX ON wege_attr (input_ref);
ANALYZE wege_iv, wege_attr;

CREATE TABLE datensatz_c.wege AS
SELECT d.id, d.art, d.input_ref AS tilda_id, a.fuehr, a.kategorie, d.reverse_cost < 0 AS einrichtung,
       round(ST_Length(d.geom)::numeric, 1) AS laenge_m, round(coalesce(v.gematcht_m, 0)::numeric, 1) AS rvn_m, v.rvn,
       d.geom::geometry(LineString, 25833) AS geom
FROM bikegraph.dc_input d
LEFT JOIN wege_iv v ON v.input_id = d.id
LEFT JOIN wege_attr a ON a.input_ref = d.input_ref
WHERE d.trace_group = 'wege';

CREATE TABLE datensatz_c.baseline_c AS
SELECT row_number() OVER (ORDER BY element_nr, ri)::bigint AS id, element_nr, ri::int AS ri, strassenname, fuehr, pflicht, breite, ofm,
       protek, tilda_id, tilda_ids, tilda_category, hmm_regel, tilda_link, ST_Multi(geom)::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_base;
CREATE TABLE datensatz_c.new_c AS
SELECT row_number() OVER (ORDER BY element_nr, ri)::bigint AS id, element_nr, ri::int AS ri, strassenname, fuehr, pflicht, breite, ofm,
       protek, tilda_id, tilda_ids, tilda_category, hmm_regel, tilda_link, ST_Multi(geom)::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_cand;

CREATE TABLE datensatz_c.diff_c AS
SELECT row_number() OVER (ORDER BY coalesce(b.element_nr, c.element_nr), coalesce(b.ri, c.ri))::bigint AS id,
       coalesce(b.element_nr, c.element_nr) AS element_nr, coalesce(b.ri, c.ri)::int AS ri, coalesce(b.strassenname, c.strassenname) AS strassenname,
       b.fuehr AS fuehr_baseline, c.fuehr AS fuehr_neu, b.tilda_ids AS tilda_ids_baseline, c.tilda_ids AS tilda_ids_neu,
       coalesce(f.urteil, CASE WHEN b.element_nr IS NULL THEN 'nur neu' WHEN c.element_nr IS NULL THEN 'nur Baseline' END) AS urteil,
       f.regel, round(f.m, 1) AS laenge_m, coalesce(b.tilda_link, c.tilda_link) AS tilda_link,
       ST_Multi(coalesce(b.geom, c.geom))::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_base b FULL JOIN bikegraph.c_cand c ON c.element_nr = b.element_nr AND c.ri = b.ri
LEFT JOIN bikegraph.c_faelle f ON f.element_nr = coalesce(b.element_nr, c.element_nr) AND f.ri = coalesce(b.ri, c.ri)
WHERE b.fuehr IS DISTINCT FROM c.fuehr
  AND NOT (coalesce(b.ri, c.ri) = 1 AND coalesce(b.element_nr, c.element_nr) IN
           (SELECT element_nr FROM matching.reference_edges WHERE verkehrsrichtung IN ('R', 'G')));

CREATE TABLE datensatz_c.baseline_wins AS SELECT * FROM datensatz_c.diff_c WHERE urteil = 'Baseline';
CREATE TABLE datensatz_c.neu_wins AS SELECT * FROM datensatz_c.diff_c WHERE urteil = 'Kandidat';

CREATE TABLE datensatz_c.diff_alle AS
WITH p AS (
    SELECT coalesce(b.element_nr, c.element_nr) AS element_nr, coalesce(b.ri, c.ri)::int AS ri,
           coalesce(b.strassenname, c.strassenname) AS strassenname,
           b.element_nr IS NULL OR c.element_nr IS NULL OR b.fuehr IS DISTINCT FROM c.fuehr AS fuehr_anders,
           b.pflicht IS DISTINCT FROM c.pflicht AS pflicht_anders,
           trim_scale(nullif(b.breite, '')::numeric) IS DISTINCT FROM trim_scale(nullif(c.breite, '')::numeric) AS breite_anders,
           b.ofm IS DISTINCT FROM c.ofm AS ofm_anders, b.farbe IS DISTINCT FROM c.farbe AS farbe_anders,
           b.protek IS DISTINCT FROM c.protek AS protek_anders, b.trennstreifen IS DISTINCT FROM c.trennstreifen AS trennstreifen_anders,
           b.nutz_beschr IS DISTINCT FROM c.nutz_beschr AS nutz_beschr_anders, b.verkehrsri IS DISTINCT FROM c.verkehrsri AS verkehrsri_anders,
           b.fuehr AS fuehr_baseline, c.fuehr AS fuehr_neu, b.pflicht AS pflicht_baseline, c.pflicht AS pflicht_neu,
           b.breite AS breite_baseline, c.breite AS breite_neu, b.ofm AS ofm_baseline, c.ofm AS ofm_neu,
           b.farbe AS farbe_baseline, c.farbe AS farbe_neu, b.protek AS protek_baseline, c.protek AS protek_neu,
           b.trennstreifen AS trennstreifen_baseline, c.trennstreifen AS trennstreifen_neu,
           b.nutz_beschr AS nutz_beschr_baseline, c.nutz_beschr AS nutz_beschr_neu,
           b.verkehrsri AS verkehrsri_baseline, c.verkehrsri AS verkehrsri_neu,
           b.tilda_ids AS tilda_ids_baseline, c.tilda_ids AS tilda_ids_neu, coalesce(c.tilda_link, b.tilda_link) AS tilda_link,
           coalesce(b.geom, c.geom) AS geom
    FROM bikegraph.c_base b FULL JOIN bikegraph.c_cand c ON c.element_nr = b.element_nr AND c.ri = b.ri
    WHERE NOT (coalesce(b.ri, c.ri) = 1 AND coalesce(b.element_nr, c.element_nr) IN
               (SELECT element_nr FROM matching.reference_edges WHERE verkehrsrichtung IN ('R', 'G'))))
SELECT row_number() OVER (ORDER BY element_nr, ri)::bigint AS id, element_nr, ri, strassenname,
       concat_ws(', ', CASE WHEN fuehr_anders THEN 'fuehr' END, CASE WHEN pflicht_anders THEN 'pflicht' END,
                 CASE WHEN breite_anders THEN 'breite' END, CASE WHEN ofm_anders THEN 'ofm' END, CASE WHEN farbe_anders THEN 'farbe' END,
                 CASE WHEN protek_anders THEN 'protek' END, CASE WHEN trennstreifen_anders THEN 'trennstreifen' END,
                 CASE WHEN nutz_beschr_anders THEN 'nutz_beschr' END, CASE WHEN verkehrsri_anders THEN 'verkehrsri' END) AS abweichend,
       (fuehr_anders::int + pflicht_anders::int + breite_anders::int + ofm_anders::int + farbe_anders::int + protek_anders::int
        + trennstreifen_anders::int + nutz_beschr_anders::int + verkehrsri_anders::int) AS anzahl,
       CASE WHEN fuehr_anders THEN coalesce(fuehr_baseline, '(leer)') END AS fuehr_baseline, CASE WHEN fuehr_anders THEN coalesce(fuehr_neu, '(leer)') END AS fuehr_neu,
       CASE WHEN pflicht_anders THEN coalesce(pflicht_baseline, '(leer)') END AS pflicht_baseline, CASE WHEN pflicht_anders THEN coalesce(pflicht_neu, '(leer)') END AS pflicht_neu,
       CASE WHEN breite_anders THEN coalesce(breite_baseline, '(leer)') END AS breite_baseline, CASE WHEN breite_anders THEN coalesce(breite_neu, '(leer)') END AS breite_neu,
       CASE WHEN ofm_anders THEN coalesce(ofm_baseline, '(leer)') END AS ofm_baseline, CASE WHEN ofm_anders THEN coalesce(ofm_neu, '(leer)') END AS ofm_neu,
       CASE WHEN farbe_anders THEN coalesce(farbe_baseline, '(leer)') END AS farbe_baseline, CASE WHEN farbe_anders THEN coalesce(farbe_neu, '(leer)') END AS farbe_neu,
       CASE WHEN protek_anders THEN coalesce(protek_baseline, '(leer)') END AS protek_baseline, CASE WHEN protek_anders THEN coalesce(protek_neu, '(leer)') END AS protek_neu,
       CASE WHEN trennstreifen_anders THEN coalesce(trennstreifen_baseline, '(leer)') END AS trennstreifen_baseline,
       CASE WHEN trennstreifen_anders THEN coalesce(trennstreifen_neu, '(leer)') END AS trennstreifen_neu,
       CASE WHEN nutz_beschr_anders THEN coalesce(nutz_beschr_baseline, '(leer)') END AS nutz_beschr_baseline,
       CASE WHEN nutz_beschr_anders THEN coalesce(nutz_beschr_neu, '(leer)') END AS nutz_beschr_neu,
       CASE WHEN verkehrsri_anders THEN coalesce(verkehrsri_baseline, '(leer)') END AS verkehrsri_baseline,
       CASE WHEN verkehrsri_anders THEN coalesce(verkehrsri_neu, '(leer)') END AS verkehrsri_neu,
       tilda_ids_baseline, tilda_ids_neu, round(ST_Length(geom)::numeric, 1) AS laenge_m, tilda_link,
       ST_Multi(geom)::geometry(MultiLineString, 25833) AS geom
FROM p
WHERE fuehr_anders OR pflicht_anders OR breite_anders OR ofm_anders OR farbe_anders OR protek_anders OR trennstreifen_anders
   OR nutz_beschr_anders OR verkehrsri_anders;

-- Straßen-Traces des RVN-Matchings (input_id 100000000 + Kante, sql/104), je Trace eine Linie in Reihenfolge der Wege
CREATE TABLE datensatz_c.strassen_traces AS
SELECT t.trace_id AS id, count(*)::int AS n_stuecke, max(t.n_wege)::int AS n_wege, sum(t.n_obs)::int AS n_obs,
       sum(t.n_gematcht)::int AS n_gematcht, sum(t.n_brueche)::int AS n_brueche,
       string_agg(t.input_ref, ', ' ORDER BY t.seq) AS wege,
       ST_Multi(ST_LineMerge(ST_Collect(t.geom ORDER BY t.seq)))::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.dc_iv_raw_traces t
WHERE t.kontext = 0 AND t.input_id BETWEEN 100000000 AND 199999999
GROUP BY t.trace_id;

ALTER TABLE datensatz_c.baseline_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.new_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.diff_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.baseline_wins ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.neu_wins ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.diff_alle ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.wege ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.strassen_traces ADD PRIMARY KEY (id);
CREATE INDEX ON datensatz_c.strassen_traces USING gist (geom);
CREATE INDEX ON datensatz_c.wege USING gist (geom);
CREATE INDEX ON datensatz_c.diff_alle USING gist (geom);
CREATE INDEX ON datensatz_c.baseline_c USING gist (geom);
CREATE INDEX ON datensatz_c.new_c USING gist (geom);
CREATE INDEX ON datensatz_c.diff_c USING gist (geom);
CREATE INDEX ON datensatz_c.baseline_wins USING gist (geom);
CREATE INDEX ON datensatz_c.neu_wins USING gist (geom);
COMMIT;
ANALYZE datensatz_c.baseline_c, datensatz_c.new_c, datensatz_c.diff_c, datensatz_c.baseline_wins, datensatz_c.neu_wins,
    datensatz_c.diff_alle, datensatz_c.wege, datensatz_c.strassen_traces;

SELECT 'baseline_c' AS tabelle, count(*) FROM datensatz_c.baseline_c UNION ALL SELECT 'new_c', count(*) FROM datensatz_c.new_c
UNION ALL SELECT 'diff_c', count(*) FROM datensatz_c.diff_c UNION ALL SELECT 'baseline_wins', count(*) FROM datensatz_c.baseline_wins
UNION ALL SELECT 'neu_wins', count(*) FROM datensatz_c.neu_wins UNION ALL SELECT 'diff_alle', count(*) FROM datensatz_c.diff_alle
UNION ALL SELECT 'wege', count(*) FROM datensatz_c.wege
UNION ALL SELECT 'strassen_traces', count(*) FROM datensatz_c.strassen_traces;
SELECT a.attribut, count(*) AS richtungen FROM datensatz_c.diff_alle, unnest(string_to_array(abweichend, ', ')) a(attribut)
GROUP BY 1 ORDER BY 2 DESC;
SELECT urteil, count(*) AS richtungen, round(sum(laenge_m) / 1000, 1) AS km FROM datensatz_c.diff_c GROUP BY 1 ORDER BY 2 DESC;
