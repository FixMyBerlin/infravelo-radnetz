-- Routing der RVN-Abschnitte, Teil 2 als Kette (aus abschnitte_2_routing.sql mit -v kette=true; Standard aus): Routen
-- ohne ganzen Weg werden nicht aus unabhängigen Teilrouten je RVN-Kante zusammengesetzt, sondern als ein
-- zusammenhängender Weg Stück für Stück entlang ihrer RVN-Kanten (Reihenfolge wie teilstueck: x, dann y).
-- 1. Stück 1 beginnt an der Startmenge seiner RVN-Kante (teil_virt). Jedes weitere Stück beginnt dort, wo der Weg bisher
--    angekommen ist: Startmenge sind die Knoten des Wegs auf den letzten :kette_m Metern (nach der letzten Brücke), je
--    mit den Kosten entlang des Wegs ab dem ersten dieser Knoten (wie die Via-Suche in Teil 4). Die Suche wählt so den
--    besten Punkt zum Weiterfahren; der Weg wird dort abgeschnitten und das neue Stück angehängt (keine Sprünge).
--    Fenster 300 m: mit 50 oder 100 m hält die Kette an parallelen Wegen ohne Querverbindung (Fahrbahn neben Radweg,
--    getrennt über mehrere hundert Meter) an der Wahl des vorigen Stücks fest, das Ziel am Ende der RVN-Kante wirkt wie
--    ein Zwangspunkt (Berlin: negative Mehrkosten in Teil 4 auf Routen aus Teilrouten 1431 ohne Kette, 5391 mit 100 m,
--    82 mit 300 m; lokal gleich wie ein unbegrenztes Fenster).
--    Ziel jedes Stücks ist die Zielmenge am Ende seiner RVN-Kante (teil_virt).
-- 2. Leere Zielmenge (kein Graph-Knoten im Fang am Kantenende): das Stück entfällt (uebersprungen), das nächste Stück
--    fährt bis zu seinem Ende und deckt die übersprungene RVN-Kante mit ab. Leere Startmenge (nur beim Neuansatz): das
--    Stück bleibt ohne Weg, der Neuansatz versucht es beim nächsten Stück.
-- 3. Kommt ein Stück nicht durch, Brücke genau an der Lücke: vom bisher erreichbaren Teil (vorwärts ab der Startmenge
--    des Stücks) zum nächsten Punkt, von dem aus das Ziel des Stücks erreichbar ist (rückwärts), Paar im Umkreis
--    :brueck_m mit den Kosten bis a + Abstand x :brueck_faktor + ab b (wie bisher). Ohne Paar dasselbe mit dem Ziel
--    des nächsten Stücks (das Stück dazwischen gilt dann als übersprungen). Danach geht die Kette ab b weiter.
-- 4. Ohne Brücke: Neuansatz wie bisher, das Stück noch einmal ab der Startmenge seiner eigenen RVN-Kante (mit Brücke ab
--    dort); gelingt auch das nicht, bleibt es ohne Weg und das nächste Stück setzt neu an. Zwischen zwei Neuansätzen
--    trennt eine virtuelle Kante (edge = -(500000000 + rid x 1000 + teil), zählt nicht; Teil 4 trennt dort die
--    Teilrouten), die Brücken behalten ihre Kennung -(1000000000 + rid x 1000 + teil).
-- 5. Mit zweitlauf (Kaskade, ZWEITLAUF=1) als letzte Option vor der Brücke: kommt ein Stück nicht durch, dasselbe Stück
--    noch einmal auf dem Graphen mit Zusatzkanten (Treppen, Erschließungsstraßen, Baustellen; faktor_plus aus graph.sql);
--    die Brücke wird dann auch auf diesem Graphen gesucht (wie Schritte 2b und 3 ohne Kette). Berlin mit Kaskade und
--    gabel_durchgehend=teilrouten: 9915 wie v7 / 64 Rückfälle (Kaskade allein 9907 / 84); 84 Routen aus Teilrouten
--    über Zusatzkanten (ohne Kette 43), Brücken 124 / 2382 m (ohne Kette 44 / 1116 m).
-- Ausgang wie Teil 2: pfad (ein Weg je Route), teilroute (art: weg, bruecke, uebersprungen, ohne; bis_knoten = Ankunft
-- des Stücks), bruecke (teil_ziel = Stück, dessen Ziel die Brücke erreicht).
-- Beidseitige Kette (von x vorwärts, von y rückwärts, Brücke wo sie sich treffen) geprüft und verworfen: bei Routen mit
-- einer Brücke liegt die beidseitige Brücke in 144 von 169 Fällen auf denselben Knoten, 7 innerhalb 25 m, 2 woanders,
-- 16 ohne Paar (nur die Kette findet eine Brücke); Kosten rund 180 ms je Route.
-- psql-Variablen: kette_m (Standard 300) und die aus abschnitte_2_routing.sql
\if :{?kette_m} \else \set kette_m 300 \endif

-- Arbeitstabellen je Route (die Funktion leert sie)
CREATE TEMP TABLE k_kanten (id bigint, source bigint, target bigint, cost float8, reverse_cost float8);
CREATE TEMP TABLE k_kanten_plus (id bigint, source bigint, target bigint, cost float8, reverse_cost float8);
CREATE TEMP TABLE k_virt (id bigint, source bigint, target bigint, cost float8);
CREATE TEMP TABLE k_weg (seq int PRIMARY KEY, node bigint, edge bigint, cost float8, len float8, sperre boolean);
CREATE TEMP TABLE k_neu (seq int, node bigint, edge bigint, cost float8, agg_cost float8);
CREATE TEMP TABLE k_vor (node bigint, k float8);
CREATE TEMP TABLE k_rueck (node bigint, k float8);
CREATE TEMP TABLE k_teil (t int PRIMARY KEY, art text, bis_knoten bigint);
CREATE INDEX ON k_vor (node); CREATE INDEX ON k_rueck (node);

-- Startmenge: aus dem bisherigen Weg (frisch = false) oder an der eigenen RVN-Kante (frisch = true); dazu die
-- Zielmenge des Stücks z. Ergebnis: Anzahl der Startknoten
CREATE FUNCTION pg_temp.kette_mengen(p_rid int, p_t int, p_z int, p_frisch boolean, p_kette_m float8) RETURNS int
LANGUAGE plpgsql AS $f$
DECLARE v_n int;
BEGIN
    TRUNCATE k_virt;
    IF p_frisch THEN
        INSERT INTO k_virt SELECT -(500000000 + row_number() OVER ()), -1, v.target, v.cost
        FROM teil_virt v WHERE v.rid = p_rid AND v.t = p_t AND v.source = -1;
    ELSE
        -- Knoten der letzten p_kette_m Meter (nach der letzten Sperre), Kennung = -seq, Kosten ab dem ersten von ihnen
        INSERT INTO k_virt SELECT -w.seq, -1, w.node, w.agg - min(w.agg) OVER ()
        FROM (SELECT x.seq, x.node, coalesce(sum(x.cost) OVER (ORDER BY x.seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS agg,
                     sum(x.len) OVER (ORDER BY x.seq DESC) AS rest
              FROM k_weg x WHERE x.seq > coalesce((SELECT max(s.seq) FROM k_weg s WHERE s.sperre), 0)) w
        WHERE w.rest <= p_kette_m;
    END IF;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    INSERT INTO k_virt SELECT v.id, v.source, v.target, v.cost FROM teil_virt v WHERE v.rid = p_rid AND v.t = p_z AND v.target = -2;
    RETURN v_n;
END $f$;

-- Ergebnis aus k_neu an den Weg hängen: beginnt es an einem Knoten des Wegs (Kennung > -500000000), wird der Weg dort
-- abgeschnitten, sonst (Neuansatz) hinten angehängt, mit Trennkante. Ergebnis: Ankunftsknoten
CREATE FUNCTION pg_temp.kette_anhaengen(p_rid int, p_t int) RETURNS bigint LANGUAGE plpgsql AS $f$
DECLARE v_erst bigint; v_p int; v_ende bigint;
BEGIN
    SELECT n.edge INTO v_erst FROM k_neu n WHERE n.seq = 1;
    IF v_erst > -500000000 AND v_erst < 0 THEN
        v_p := -v_erst;
        DELETE FROM k_weg WHERE seq >= v_p;
    ELSE
        SELECT coalesce(max(seq), 0) + 1 INTO v_p FROM k_weg;
        UPDATE k_weg SET edge = -(500000000 + p_rid * 1000 + p_t), cost = 0, len = 0, sperre = true WHERE seq = v_p - 1;
    END IF;
    INSERT INTO k_weg
    SELECT v_p - 1 + row_number() OVER (ORDER BY n.seq), n.node, CASE WHEN n.edge < 0 THEN -1 ELSE n.edge END,
           CASE WHEN n.edge < 0 THEN 0 ELSE n.cost END, coalesce(g.len, 0), false
    FROM k_neu n LEFT JOIN routing_graph.g g ON g.id = n.edge AND n.edge >= 0 WHERE n.node >= 0;
    SELECT node INTO v_ende FROM k_weg ORDER BY seq DESC LIMIT 1;
    RETURN v_ende;
END $f$;

-- Brücke für Stück t ab der Startmenge in k_virt: Ziele t, dann t + 1. Ergebnis: Stück, dessen Ziel erreicht wurde
-- (NULL ohne Brücke); Weg Start -> a, Brücke, b -> Ziel am Weg
CREATE FUNCTION pg_temp.kette_bruecke(p_rid int, p_t int, p_n int, p_brueck_m float8, p_faktor float8, p_q text) RETURNS int LANGUAGE plpgsql AS $f$
DECLARE v_z int; v_br record; v_a_seq int;
BEGIN
    TRUNCATE k_vor;
    EXECUTE format('INSERT INTO k_vor SELECT d.node, d.agg_cost FROM pgr_drivingDistance(%L, -1::bigint, 1e9::float8, true) d WHERE d.node >= 0', p_q);
    ANALYZE k_vor;
    FOR v_z IN p_t .. least(p_t + 1, p_n) LOOP
        CONTINUE WHEN NOT EXISTS (SELECT 1 FROM teil_virt v WHERE v.rid = p_rid AND v.t = v_z AND v.target = -2);
        DELETE FROM k_virt WHERE target = -2;
        INSERT INTO k_virt SELECT v.id, v.source, v.target, v.cost FROM teil_virt v WHERE v.rid = p_rid AND v.t = v_z AND v.target = -2;
        -- Ziel des nächsten Stücks ohne Brücke erreichbar: dann dorthin (Stück t übersprungen)
        IF v_z > p_t THEN
            TRUNCATE k_neu;
            EXECUTE format('INSERT INTO k_neu SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d', p_q);
            IF EXISTS (SELECT 1 FROM k_neu) THEN
                PERFORM pg_temp.kette_anhaengen(p_rid, p_t);
                RETURN -v_z;
            END IF;
        END IF;
        TRUNCATE k_rueck;
        EXECUTE format('INSERT INTO k_rueck SELECT d.node, d.agg_cost FROM pgr_drivingDistance(%L, -2::bigint, 1e9::float8, true) d WHERE d.node >= 0',
                       format('SELECT id, target AS source, source AS target, cost, reverse_cost FROM (%s) x', p_q));
        ANALYZE k_rueck;
        SELECT v.node AS a, w.node AS b, v.k AS kv, w.k AS kr, ST_Distance(ka.geom, kb.geom) AS d, ST_MakeLine(ka.geom, kb.geom) AS geom
        INTO v_br
        FROM k_vor v JOIN routing_graph.knoten ka ON ka.id = v.node
        JOIN routing_graph.knoten kb ON ST_DWithin(kb.geom, ka.geom, p_brueck_m) JOIN k_rueck w ON w.node = kb.id
        ORDER BY v.k + ST_Distance(ka.geom, kb.geom) * p_faktor + w.k LIMIT 1;
        IF FOUND THEN
            -- Start -> a (schneidet den Weg wie ein Stück), dann die Brücke als Sperre, dann b -> Ziel
            TRUNCATE k_neu;
            EXECUTE format('INSERT INTO k_neu SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, %s::bigint, true) d', p_q, v_br.a);
            PERFORM pg_temp.kette_anhaengen(p_rid, p_t);
            SELECT max(seq) INTO v_a_seq FROM k_weg;
            UPDATE k_weg SET edge = -(1000000000 + p_rid * 1000 + p_t), cost = v_br.d * p_faktor, len = 0, sperre = true WHERE seq = v_a_seq;
            TRUNCATE k_neu;
            EXECUTE format('INSERT INTO k_neu SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, %s::bigint, -2::bigint, true) d', p_q, v_br.b);
            INSERT INTO k_weg
            SELECT v_a_seq + row_number() OVER (ORDER BY n.seq), n.node, CASE WHEN n.edge < 0 THEN -1 ELSE n.edge END,
                   CASE WHEN n.edge < 0 THEN 0 ELSE n.cost END, coalesce(g.len, 0), false
            FROM k_neu n LEFT JOIN routing_graph.g g ON g.id = n.edge AND n.edge >= 0 WHERE n.node >= 0;
            INSERT INTO bruecke (rid, teil, a, b, laenge, kosten_vor, kosten_rueck, geom, teil_ziel)
            VALUES (p_rid, p_t, v_br.a, v_br.b, v_br.d, v_br.kv, v_br.kr, v_br.geom, v_z);
            RETURN v_z;
        END IF;
    END LOOP;
    RETURN NULL;
END $f$;

-- Kette je Route
CREATE FUNCTION pg_temp.kette(p_rid int, p_kette_m float8, p_brueck_m float8, p_faktor float8, p_zweit boolean) RETURNS int
LANGUAGE plpgsql AS $f$
DECLARE v_n int; v_i int := 1; v_frisch boolean := true; v_z int; v_q text; v_q_plus text; v_saat int; v_ok boolean; v_versuch int;
BEGIN
    TRUNCATE k_kanten, k_kanten_plus, k_weg, k_teil;
    INSERT INTO k_kanten
    SELECT g.id, g.source, g.target,
           CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len * (g.faktor0 + k.zusatz_je_m) END,
           CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len * (g.faktor1 + k.zusatz_je_m) END
    FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = p_rid;
    v_q := 'SELECT id, source, target, cost, reverse_cost FROM k_kanten UNION ALL SELECT id, source, target, cost, -1::float8 FROM k_virt';
    IF p_zweit THEN
        INSERT INTO k_kanten_plus
        SELECT g.id, g.source, g.target,
               CASE WHEN coalesce(g.faktor0, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor0, g.faktor_plus) + k.zusatz_je_m) END,
               CASE WHEN coalesce(g.faktor1, g.faktor_plus) IS NULL THEN -1 ELSE g.len * (coalesce(g.faktor1, g.faktor_plus) + k.zusatz_je_m) END
        FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = p_rid;
    END IF;
    v_q_plus := 'SELECT id, source, target, cost, reverse_cost FROM k_kanten_plus UNION ALL SELECT id, source, target, cost, -1::float8 FROM k_virt';
    SELECT max(s.t) INTO v_n FROM teilstueck s WHERE s.rid = p_rid;
    WHILE v_i <= v_n LOOP
        IF NOT EXISTS (SELECT 1 FROM teil_virt v WHERE v.rid = p_rid AND v.t = v_i AND v.target = -2) THEN
            INSERT INTO k_teil VALUES (v_i, 'uebersprungen', NULL);
            v_i := v_i + 1; CONTINUE;
        END IF;
        v_ok := false;
        -- erst ab dem bisherigen Weg, dann (Neuansatz) ab der eigenen Startmenge
        FOR v_versuch IN 1..2 LOOP
            CONTINUE WHEN v_versuch = 2 AND v_frisch;
            v_saat := pg_temp.kette_mengen(p_rid, v_i, v_i, v_frisch OR v_versuch = 2, p_kette_m);
            CONTINUE WHEN v_saat = 0;
            TRUNCATE k_neu;
            EXECUTE format('INSERT INTO k_neu SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d', v_q);
            -- letzte Option vor der Brücke: dasselbe Stück mit Zusatzkanten
            IF p_zweit AND NOT EXISTS (SELECT 1 FROM k_neu) THEN
                EXECUTE format('INSERT INTO k_neu SELECT d.seq, d.node, d.edge, d.cost, d.agg_cost FROM pgr_dijkstra(%L, -1::bigint, -2::bigint, true) d', v_q_plus);
            END IF;
            IF EXISTS (SELECT 1 FROM k_neu) THEN
                INSERT INTO k_teil VALUES (v_i, 'weg', pg_temp.kette_anhaengen(p_rid, v_i));
                v_ok := true; v_z := v_i;
            ELSE
                v_z := pg_temp.kette_bruecke(p_rid, v_i, v_n, p_brueck_m, p_faktor, CASE WHEN p_zweit THEN v_q_plus ELSE v_q END);
                IF v_z IS NOT NULL THEN
                    v_ok := true;
                    IF v_z < 0 THEN   -- nächstes Ziel ohne Brücke erreicht
                        v_z := -v_z;
                        INSERT INTO k_teil VALUES (v_i, 'uebersprungen', NULL);
                    ELSE
                        INSERT INTO k_teil VALUES (v_i, 'bruecke', (SELECT node FROM k_weg ORDER BY seq DESC LIMIT 1));
                    END IF;
                    IF v_z > v_i THEN
                        INSERT INTO k_teil VALUES (v_z, 'weg', (SELECT node FROM k_weg ORDER BY seq DESC LIMIT 1));
                    END IF;
                END IF;
            END IF;
            EXIT WHEN v_ok;
        END LOOP;
        IF v_ok THEN
            v_frisch := false; v_i := v_z + 1;
        ELSE
            INSERT INTO k_teil VALUES (v_i, 'ohne', NULL);
            v_frisch := true; v_i := v_i + 1;
        END IF;
    END LOOP;
    INSERT INTO pfad
    SELECT p_rid, w.seq, w.node, w.edge, w.cost, coalesce(sum(w.cost) OVER (ORDER BY w.seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
    FROM k_weg w;
    INSERT INTO teilroute (rid, teil, rvn_id, ri, mit_weg, mit_bruecke, art, bis_knoten)
    SELECT p_rid, s.t, s.rvn_id, s.ri, k.art <> 'ohne', k.art = 'bruecke', k.art, k.bis_knoten
    FROM teilstueck s JOIN k_teil k ON k.t = s.t WHERE s.rid = p_rid;
    RETURN (SELECT count(*) FROM k_weg)::int;
END $f$;

SELECT format('SELECT pg_temp.kette(%s, %s, %s, %s, %L)', o.rid, :kette_m, :brueck_m, :brueck_faktor, :zweitlauf)
FROM ohne_weg o ORDER BY o.rid \gexec
