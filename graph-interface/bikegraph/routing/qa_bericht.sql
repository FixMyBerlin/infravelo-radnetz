-- Zusammenfassung des QA-Laufs (routing_qa.sh): Übereinstimmung mit v7, Urteile der Unterschiede, auffällige Stellen.
-- psql-Variablen: lang_m (lange Kreuzungsstücke ab so vielen Metern, Standard 50)
\if :{?lang_m} \else \set lang_m 50 \endif
\echo 'Übereinstimmung mit v7 je RVN-Kantenrichtung'
SELECT count(*) AS kantenrichtungen, count(*) FILTER (WHERE v7 IS NOT NULL) AS mit_v7,
       count(*) FILTER (WHERE routing = v7) AS wie_v7, count(*) FILTER (WHERE rueckfall) AS ohne_weg_rueckfall
FROM routing_martin.routing_rvn;
\echo 'Unterschiede zu v7 nach Urteil (Belege vor Ort, martin_beurteilung.sql)'
SELECT urteil, grund, count(*) AS faelle, round(sum(laenge_m) / 1000, 1) AS km FROM (
    SELECT urteil, grund, laenge_m FROM routing_martin.routing_urteil_routing UNION ALL
    SELECT urteil, grund, laenge_m FROM routing_martin.routing_urteil_v7 UNION ALL
    SELECT urteil, grund, laenge_m FROM routing_martin.routing_urteil_grenzfall) x
GROUP BY 1, 2 ORDER BY 1, 3 DESC;
\echo 'Unbequeme Verbindungen (Treppen, Erschließungsstraßen, Baustellen von Routen benutzt; Brücken über Netzlücken)'
SELECT art, count(*) AS stellen, sum(routen) AS routen, round(sum(m)) AS m FROM routing_martin.routing_unbequem GROUP BY 1 ORDER BY 2 DESC;
\echo 'Kreuzungsstücke (lang ab lang_m)'
SELECT count(*) AS kreuzungsstuecke, count(*) FILTER (WHERE m >= :lang_m) AS lang,
       count(DISTINCT knoten) FILTER (WHERE m >= :lang_m) AS kreuzungen_mit_langem_stueck, round(max(m)) AS laengstes_m
FROM routing_martin.routing_crossings;
\echo 'Abbrüche: Abschnitte ohne durchgehenden Weg, nach grober Ursache'
SELECT coalesce(split_part(ursache, ':', 1), '-') AS ursache, count(*) AS abschnitte FROM routing_martin.routing_luecken GROUP BY 1 ORDER BY 2 DESC;
