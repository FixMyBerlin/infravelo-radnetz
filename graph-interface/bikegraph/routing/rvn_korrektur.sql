-- Korrigierte Kopie der RVN-Rohdaten (matching_staging.reference_raw, aus vorrangnetz_details_combined_rvn.fgb) in
-- matching_korr.reference_raw, mit den sicheren Befunden aus sonderfaelle/README.md ("Befunde in den RVN-Daten"):
-- 1. Doppelte Kanten entfernt: die Sackgassen-Stummel und die Kante mit zwei Sackgassen (Großer Stern), die ganz auf
--    anderen RVN-Kanten liegen; die Kanten darunter sind die richtigen und bleiben. Die Teilüberdeckung
--    (43620001_V4396.01 / 43620001_43630001.02) bleibt, weil offen ist, welche der beiden richtig ist.
-- 2. Putlitzbrücke: die Anbindung der Quitzowstraße an die Brücke (42560036_42560035.01, 30 m) führt über eine Treppe
--    (OSM highway=steps, Weg 10638); an der Brücke gibt es dort keine Verbindung mit dem Rad. Die Kante bleibt (Element
--    für Datensatz C), wird am Brückenknoten 42560035 aber gelöst: Ende 1 m vor dem Knoten, endet_bei_vp V42560035-T.
--    Die Putlitzbrücke läuft damit ohne Kreuzung durch. Dafür neue Kante 42560036_42560004.01 (305 m): von der
--    Quitzowstraße (Knoten 42560036) die Putlitzstraße hinunter und über die nördliche Fahrbahn der Birkenstraße zum
--    vorhandenen Knoten 42560004 (Ecke Putlitzbrücke / Birkenstraße / Stromstraße). Geometrie aus den OSM-Kanten
--    (bikegraph.edges 6654, 6655, 868844, 85488, 85489, 85490, 85491, 641968, dann 702792, 563381, 563380 umgedreht),
--    Enden genau auf den beiden RVN-Knoten, als feste Koordinaten; der Süden der Putlitzstraße ist in OSM Baustelle.
--    edge_source korrektur, verkehrsrichtung B wie die Detailnetz-Kanten daneben.
-- Ausgang: matching_korr.reference_raw (gleiche Spalten wie die Rohdaten), matching_korr.korrektur (je Änderung das
-- Element, die Art und für entfernte Kanten die Elemente darunter, auf die ihr Ergebnis übertragen werden kann).
-- Export als FlatGeobuf: rvn_korrektur.sh.
BEGIN;
DROP SCHEMA IF EXISTS matching_korr CASCADE;
CREATE SCHEMA matching_korr;
CREATE TABLE matching_korr.korrektur (element_nr text, ogc_fid int, art text, element_darunter text, beschreibung text);
INSERT INTO matching_korr.korrektur (element_nr, art, element_darunter, beschreibung) VALUES
 ('43540002_44550041.01', 'entfernt', '43540002_44550041.01', 'Großer Stern / Magnus-Hirschfeld-Ufer: 1046 m, beide Enden Sackgasse, liegt ganz auf der Kette desselben Elements'),
 ('49590026_49590049.01', 'entfernt', '49590025_49590026.02, 49590026_49580038.01', 'KGA Frieden: Sackgassen-Stummel (362 m) auf anderer Kante'),
 ('55560007_55560186.01', 'entfernt', '55560007_56560038.02, 55560007_56560042.02', 'Murtzaner Ring: Sackgassen-Stummel (127 m) auf anderer Kante'),
 ('51630294_51630020.01', 'entfernt', '51630004_51630020.02, 51630019_51630020.02', 'Straße 27: Sackgassen-Stummel (121 m) auf anderer Kante'),
 ('53670002_53670003.02', 'entfernt', '53670002_53670003.01, 53670003_53670315.01', 'Alt-Buch: Sackgassen-Stummel (111 m) auf anderer Kante'),
 ('49520010_49520011.04', 'entfernt', '49520009_49520010.02, 49520010_49520011.03', 'Falckensteinstraße: Sackgassen-Stummel (98 m) auf anderer Kante'),
 ('50570039_50570223.01', 'entfernt', '50570039_50570034.02, 50580010_50570039.02', 'Mahlerstraße: Sackgassen-Stummel (42 m) auf anderer Kante'),
 ('42560036_42560035.01', 'gelöst', NULL, 'Putlitzbrücke: Anbindung der Quitzowstraße über eine Treppe (OSM Weg 10638), am Brückenknoten 42560035 gelöst'),
 ('42560036_42560004.01', 'neu', NULL, 'Putlitzbrücke: neue Verbindung der Quitzowstraße über Putlitzstraße und Birkenstraße zum Knoten 42560004 (Ecke Putlitzbrücke / Birkenstraße), statt der Treppe');
-- Rohdaten-Zeile je Korrektur: entfernte Kanten sind die mit Verkehrsrichtung B (die Kanten darunter haben keine);
-- beim Großen Stern teilen sich drei Zeilen das Element, die entfernte ist die mit Straßennamen
UPDATE matching_korr.korrektur k SET ogc_fid = r.ogc_fid
FROM matching_staging.reference_raw r
WHERE r.element_nr = k.element_nr AND (k.art = 'gelöst' OR (k.art = 'entfernt' AND r.verkehrsrichtung = 'B'));
UPDATE matching_korr.korrektur SET ogc_fid = (SELECT max(ogc_fid) + 1 FROM matching_staging.reference_raw) WHERE art = 'neu';
DO $$ BEGIN
  IF (SELECT count(*) FROM matching_korr.korrektur WHERE ogc_fid IS NULL) > 0
     OR EXISTS (SELECT 1 FROM matching_staging.reference_raw WHERE element_nr = '42560036_42560004.01')
     OR (SELECT count(DISTINCT element_nr) FROM matching_korr.korrektur) <> (SELECT count(*) FROM matching_korr.korrektur) THEN
    RAISE EXCEPTION 'Korrektur: Rohdaten-Zeilen nicht eindeutig gefunden';
  END IF;
END $$;
CREATE TABLE matching_korr.reference_raw AS
SELECT r.* FROM matching_staging.reference_raw r
LEFT JOIN matching_korr.korrektur k ON k.ogc_fid = r.ogc_fid AND k.art = 'entfernt'
WHERE k.ogc_fid IS NULL;
UPDATE matching_korr.reference_raw r
SET geom = ST_Multi(ST_LineSubstring(ST_GeometryN(r.geom, 1), 0, 1 - 1.0 / ST_Length(ST_GeometryN(r.geom, 1)))),
    endet_bei_vp = 'V42560035-T'
FROM matching_korr.korrektur k WHERE k.art = 'gelöst' AND k.ogc_fid = r.ogc_fid AND r.endet_bei_vp = '42560035';
DO $$ BEGIN
  IF (SELECT count(*) FROM matching_korr.reference_raw WHERE endet_bei_vp = 'V42560035-T') <> 1 THEN
    RAISE EXCEPTION 'Korrektur: Putlitzbrücke nicht gelöst';
  END IF;
END $$;
INSERT INTO matching_korr.reference_raw (ogc_fid, element_nr, strassenname, strassenklasse, verkehrsrichtung, beginnt_bei_vp, endet_bei_vp, edge_source, geom)
SELECT k.ogc_fid, k.element_nr, 'Putlitzstraße', NULL, 'B', '42560036', '42560004', 'korrektur',
       ST_Multi(ST_GeomFromText('LINESTRING(387620.34 5821765.29,387620.49 5821765.94,387620.1 5821756.45,387619.99 5821753.57,'
         '387617.15 5821683.95,387616.32 5821673.07,387615.42 5821654.21,387614.94 5821643.85,387613.72 5821617.86,'
         '387608.81 5821513.41,387607.38 5821509.8,387606.02 5821507.58,387603.87 5821504.76,387596.56 5821497.22,'
         '387604.52 5821495.1,387607.52 5821494.29,387617.83 5821489.5,387620.58 5821481.79)', 25833))
FROM matching_korr.korrektur k WHERE k.art = 'neu';
-- Enden genau auf die Kantenenden daneben (Ende Quitzowstraße 42560024_42560036.01, Anfang 42560004_42560032.01)
UPDATE matching_korr.reference_raw n
SET geom = ST_Multi(ST_SetPoint(ST_SetPoint(ST_GeometryN(n.geom, 1), 0, ST_EndPoint(ST_GeometryN(q.geom, 1))),
                                ST_NPoints(ST_GeometryN(n.geom, 1)) - 1, ST_StartPoint(ST_GeometryN(b.geom, 1))))
FROM matching_korr.reference_raw q, matching_korr.reference_raw b
WHERE n.element_nr = '42560036_42560004.01' AND q.element_nr = '42560024_42560036.01' AND b.element_nr = '42560004_42560032.01';
-- Enden der neuen Kante liegen auf den Enden der Nachbarkanten (Knoten 42560036 und 42560004, Toleranz wie 01_reference.sql)
DO $$ BEGIN
  IF (SELECT count(*) FROM matching_korr.reference_raw n, matching_korr.reference_raw r
      WHERE n.element_nr = '42560036_42560004.01' AND r.ogc_fid <> n.ogc_fid
        AND (ST_DWithin(ST_StartPoint(ST_GeometryN(n.geom, 1)), ST_EndPoint(ST_GeometryN(r.geom, 1)), 0.01)
             OR ST_DWithin(ST_StartPoint(ST_GeometryN(n.geom, 1)), ST_StartPoint(ST_GeometryN(r.geom, 1)), 0.01))) = 0
     OR (SELECT count(*) FROM matching_korr.reference_raw n, matching_korr.reference_raw r
      WHERE n.element_nr = '42560036_42560004.01' AND r.ogc_fid <> n.ogc_fid
        AND (ST_DWithin(ST_EndPoint(ST_GeometryN(n.geom, 1)), ST_EndPoint(ST_GeometryN(r.geom, 1)), 0.01)
             OR ST_DWithin(ST_EndPoint(ST_GeometryN(n.geom, 1)), ST_StartPoint(ST_GeometryN(r.geom, 1)), 0.01))) = 0 THEN
    RAISE EXCEPTION 'Korrektur: neue Kante Putlitzstraße trifft die RVN-Knoten nicht';
  END IF;
END $$;
ALTER TABLE matching_korr.reference_raw ADD PRIMARY KEY (ogc_fid);
COMMIT;
\echo 'Rohdaten vorher, nachher, Korrekturen'
SELECT (SELECT count(*) FROM matching_staging.reference_raw) AS vorher, (SELECT count(*) FROM matching_korr.reference_raw) AS nachher,
       (SELECT count(*) FILTER (WHERE art = 'entfernt') FROM matching_korr.korrektur) AS entfernt,
       (SELECT count(*) FILTER (WHERE art = 'gelöst') FROM matching_korr.korrektur) AS geloest,
       (SELECT count(*) FILTER (WHERE art = 'neu') FROM matching_korr.korrektur) AS neu;
