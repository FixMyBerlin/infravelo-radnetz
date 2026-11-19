/* sql-formatter-disable */
-- _qa_features for a bikelanes reference, like tilda-geo
-- processing/topics/roads_bikelanes/5_qa_bikelanes.sql: every line with its `length` as amount,
-- on its street side.
-- :shift = true: the export has the road centerline plus `offset` (TILDA since August 2026), so the
--   lines are moved to their side with tilda_qa_side_lines, exactly like the nightly.
-- :shift = false: the export geometry is already on its side (TILDA exports until August 2026,
--   e.g. the 2026-01-29 export behind data.infravelo_qa_2026_reference_rvn).
-- INPUT: _tilda_qa_reference.bikelanes (TILDA bikelanes export), psql variable :shift
CREATE TEMP TABLE _qa_features AS
SELECT
  b.geom,
  -- the tagged length, split over the parts of a multi line by part length
  (COALESCE((b.tags ->> 'length')::FLOAT, b.full_length) * ST_Length(b.geom) / b.full_length)::NUMERIC AS amount,
  tilda_qa_bikelane_tags(b.tags) AS tags,
  COALESCE((b.tags ->> 'offset')::NUMERIC, 0) AS offset_m
FROM (
  SELECT
    jsonb_strip_nulls(to_jsonb(t) - 'geom' - 'ogc_fid') AS tags,
    (ST_Dump(ST_Transform(t.geom, 5243))).geom AS geom,
    ST_Length(ST_Transform(t.geom, 5243)) AS full_length
  FROM _tilda_qa_reference.bikelanes t
) b
WHERE ST_GeometryType(b.geom) = 'ST_LineString' AND ST_Length(b.geom) > 0;

\if :shift
  CREATE TEMP TABLE _qa_features_side AS
  SELECT side.geom, f.amount * side.share::NUMERIC AS amount, f.tags
  FROM _qa_features f
  CROSS JOIN LATERAL tilda_qa_side_lines(f.geom, f.offset_m) side;
  DROP TABLE _qa_features;
  ALTER TABLE _qa_features_side RENAME TO _qa_features;
\else
  ALTER TABLE _qa_features DROP COLUMN offset_m;
\endif
