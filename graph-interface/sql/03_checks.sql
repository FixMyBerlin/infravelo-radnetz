-- Prüfungen der Schnittstelle. Jede Zeile: Prüfung, Wert, ok.

WITH
ref_end_offsets AS (
    SELECT greatest(ST_Distance(ST_StartPoint(e.geom), s.geom), ST_Distance(ST_EndPoint(e.geom), t.geom)) AS d
    FROM matching.reference_edges e
    JOIN matching.reference_vertices s ON s.id = e.source
    JOIN matching.reference_vertices t ON t.id = e.target
),
inp_end_offsets AS (
    SELECT greatest(ST_Distance(ST_StartPoint(e.geom), s.geom), ST_Distance(ST_EndPoint(e.geom), t.geom)) AS d
    FROM matching.input_edges e
    JOIN matching.input_vertices s ON s.id = e.source
    JOIN matching.input_vertices t ON t.id = e.target
),
checks(name, value, ok) AS (
    SELECT 'reference: edges', count(*)::text, count(*) > 0 FROM matching.reference_edges
    UNION ALL SELECT 'reference: vertices', count(*)::text, count(*) > 0 FROM matching.reference_vertices
    UNION ALL SELECT 'reference: edges without vertex', count(*)::text, count(*) = 0
        FROM matching.reference_edges e
        WHERE NOT EXISTS (SELECT 1 FROM matching.reference_vertices v WHERE v.id = e.source)
           OR NOT EXISTS (SELECT 1 FROM matching.reference_vertices v WHERE v.id = e.target)
    UNION ALL SELECT 'reference: max end-to-vertex offset (m)', round(max(d)::numeric, 4)::text, max(d) <= 0.05 FROM ref_end_offsets
    UNION ALL SELECT 'reference: cost <= 0', count(*)::text, count(*) = 0 FROM matching.reference_edges WHERE cost <= 0
    UNION ALL SELECT 'reference: one-way edges', count(*)::text, true FROM matching.reference_edges WHERE reverse_cost < 0
    UNION ALL SELECT 'reference: invalid geometry', count(*)::text, count(*) = 0 FROM matching.reference_edges WHERE NOT ST_IsValid(geom) OR ST_SRID(geom) <> 25833
    UNION ALL SELECT 'input: edges', count(*)::text, count(*) > 0 FROM matching.input_edges
    UNION ALL SELECT 'input: vertices', count(*)::text, count(*) > 0 FROM matching.input_vertices
    UNION ALL SELECT 'input: edges without source/target', count(*)::text, count(*) = 0 FROM matching.input_edges WHERE source IS NULL OR target IS NULL
    UNION ALL SELECT 'input: max end-to-vertex offset (m)', round(max(d)::numeric, 4)::text, max(d) <= 0.05 FROM inp_end_offsets
    UNION ALL SELECT 'input: cost <= 0', count(*)::text, count(*) = 0 FROM matching.input_edges WHERE cost <= 0
    UNION ALL SELECT 'input: one-way edges', count(*)::text, true FROM matching.input_edges WHERE reverse_cost < 0
    UNION ALL SELECT 'input: edges per trace_group', string_agg(trace_group || '=' || n, ' ' ORDER BY trace_group), true
        FROM (SELECT trace_group, count(*) n FROM matching.input_edges GROUP BY 1) g
    UNION ALL SELECT 'input: share with match_key', round(100.0 * count(match_key) / count(*), 1)::text || ' %', true FROM matching.input_edges
    UNION ALL SELECT 'reference: share with match_key', round(100.0 * count(match_key) / count(*), 1)::text || ' %', true FROM matching.reference_edges
)
SELECT name, value, CASE WHEN ok THEN 'ok' ELSE 'FEHLER' END AS status FROM checks;
