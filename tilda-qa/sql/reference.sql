/* sql-formatter-disable */
-- WHAT IT DOES:
-- Write a QA reference table from a frozen delivery, with the QA functions of tilda-geo
-- (processing/qa/qa_functions.sql), so the reference is measured exactly like the nightly measures
-- the current data: a feature that crosses a cell border counts in each cell with the share that
-- lies inside.
-- INPUT: _qa_features from :features_file (bikelanes.sql), the cell table,
--        psql variables :features_file, :area_table, :indicators, :target (and :shift for bikelanes.sql)
-- OUTPUT: data.:target (area_id, indicator_key, value_key, amount)
--
DROP TABLE IF EXISTS pg_temp._qa_features;
\i :features_file
ALTER TABLE _qa_features ADD COLUMN osm_user TEXT, ADD COLUMN updated_at BIGINT;
CREATE INDEX ON _qa_features USING GIST (geom);
ANALYZE _qa_features;

CALL tilda_qa_prepare_config(:'area_table', :'indicators'::JSONB);
CALL tilda_qa_measure();

DROP TABLE IF EXISTS data.:"target";
CREATE TABLE data.:"target" (
  area_id TEXT,
  indicator_key TEXT,
  value_key TEXT,
  amount NUMERIC,
  PRIMARY KEY (area_id, indicator_key, value_key)
);
INSERT INTO data.:"target" SELECT * FROM _qa_current ORDER BY 1, 2, 3;
