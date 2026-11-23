"""Routing der RVN-Abschnitte, Teil 2s (abschnitte.sh mit STEINER=1, nach Teil 2, vor Teil 3): Wege je RVN-Kreuzung
gemeinsam als gerichteter Steiner-Wald (exakt als MILP, HiGHS über scipy).

Je Kreuzung b (Ende des ankommenden Abschnitts x) alle Routen x -> y, die in Teil 2 einen durchgehenden Weg haben (keine
Teilrouten, keine Zusatzkanten). Gesucht ist je Route ein Weg von ihrer Startmenge zu ihrer Zielmenge (virt) über ihre
Korridorkanten (korridor_kanten, Richtung wie in Teil 2), so dass
    Summe über die Vereinigung der benutzten Kanten  C_e                      (jede Kante einmal)
  + lambda x Summe je Route ihrer Kosten wie in Teil 2  Länge x (Faktor + zusatz_je_m) + umweg
  + Summe je Route ihrer Anschlusskosten (virtuelle Kanten)
minimal ist; C_e = Länge x (kleinster Faktor der Kante + kleinster zusatz_je_m der Routen) + kleinster umweg. Eine Kante,
die schon eine Route außerhalb der Kreuzung benutzt (Nachbarkreuzungen, Teilrouten, Zusatzkanten; aktueller Stand in pfad),
gilt als bezahlt (C_e = 0): die Vereinigung ist über alle Kreuzungen gemeinsam, die Kreuzungen teilen ihre Wege. Mehrere
Runden (abschnitte.sh, STEINER_RUNDEN) lösen jede Kreuzung mit dem neuesten Stand der Nachbarn neu. Eine Kante,
die schon eine andere Route benutzt, kostet also nur noch lambda x ihre Kosten: die Routen einer Kreuzung teilen sich die
Wege, wo der Umweg klein ist (lambda = 0: reiner Steiner-Wald, groß: unabhängige kürzeste Wege wie in Teil 2).
Modell: x_e binär je Kante, f je Route und Bogen (0..1), Flusserhaltung je Route, f <= x_e.
Die Wege der Routen ersetzen ihre Wege in pfad (Format von pgr_dijkstra, mit den virtuellen Start- und Zielkanten).
Ohne Lösung in :zeit s oder ohne Weg für eine Route bleibt Teil 2. Protokoll je Kreuzung in steiner.
--nachbar: die Enden der Routen hängen am Netz der Nachbarkreuzungen statt fest am RVN-Knoten. Eine Route x -> y darf
zusätzlich an jedem Knoten einer Route y -> z der nächsten Kreuzung enden und an jedem Knoten einer Route v -> x der
vorigen Kreuzung beginnen, jeweils ohne Anschlusskosten (virtuelle Kanten -1800000000 - j / -1900000000 - j), nur an
Knoten auf der eigenen Seite (Start näher an x, Ziel näher an y), damit jede Route ihre Kreuzung selbst fährt; Start- und
Zielmenge aus virt bleiben. So enden die Routen dort, wo die Nachbarkreuzung übernimmt, statt mit einem Stummel bis zum
RVN-Knoten. Lückenlos nur, wenn benachbarte Kreuzungen nicht gleichzeitig gelöst werden: --faerben färbt die Kreuzungen
einmal (steiner_farbe, Nachbarn = über einen Abschnitt verbunden, verschiedene Farben), --farbe F löst nur die Kreuzungen
der Farbe F; abschnitte.sh löst die Farben nacheinander, je Farbe parallel.

Aufruf: abschnitte_2s_steiner.py --schema S --teil T --teile N [--lambda 0.7] [--zeit 120] [--knoten b1,b2] [--runde 1]
        [--allein] [--nachbar] [--farbe F] [--faerben]
        (--allein: ohne die bezahlten Kanten der Nachbarn, jede Kreuzung für sich)
Verbindung: MATCHING_PG (libpq-Verbindungstext), Passwort aus PGPASSWORD. Braucht scipy (>= 1.9) und psycopg2.
"""
import argparse
import os
import time
from collections import defaultdict

import numpy as np
import psycopg2
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

ap = argparse.ArgumentParser()
ap.add_argument("--schema", default="routing_abschnitte")
ap.add_argument("--teil", type=int, default=0)
ap.add_argument("--teile", type=int, default=1)
ap.add_argument("--lambda", dest="lam", type=float, default=0.7)
ap.add_argument("--zeit", type=float, default=120)
ap.add_argument("--knoten", default="")
ap.add_argument("--runde", type=int, default=1)
ap.add_argument("--allein", action="store_true")
ap.add_argument("--nachbar", action="store_true")
ap.add_argument("--farbe", type=int, default=-1)
ap.add_argument("--faerben", action="store_true")
a = ap.parse_args()

con = psycopg2.connect(os.environ["MATCHING_PG"])
con.autocommit = False
cur = con.cursor()
cur.execute(f'SET search_path TO "{a.schema}", public')
if a.teil == 0:
    cur.execute("""CREATE TABLE IF NOT EXISTS steiner (b bigint, routen int, kanten int, boegen int, status text, sekunden float8,
                   ziel float8, ziel_teil2 float8, vereinigung_m float8, vereinigung_teil2_m float8, geaendert int, runde int, bezahlt int)""")
    con.commit()

# Routen je Kreuzung: durchgehend in Teil 2 (keine Teilroute, keine Zusatzkanten)
cur.execute("""
SELECT ax.nach AS b, r.rid FROM routen r JOIN abschnitte ax ON ax.abschnitt = r.x
WHERE r.y IS NOT NULL AND EXISTS (SELECT 1 FROM pfad p WHERE p.rid = r.rid)
  AND NOT EXISTS (SELECT 1 FROM teilroute t WHERE t.rid = r.rid)
  AND NOT EXISTS (SELECT 1 FROM zweitlauf z WHERE z.rid = r.rid)""")
je_b = defaultdict(list)
for b, rid in cur.fetchall():
    je_b[b].append(rid)
nur = {int(x) for x in a.knoten.split(",") if x}
knoten = sorted(b for b, rs in je_b.items() if len(rs) >= 2 and (not nur or b in nur))

if a.faerben:
    # Nachbarn: Kreuzungen, die ein Abschnitt verbindet (Anfang und Ende eines Abschnitts x einer Route); gierig färben,
    # Kreuzungen mit den meisten Nachbarn zuerst
    cur.execute("SELECT DISTINCT von, nach FROM abschnitte WHERE von <> nach")
    nachbarn = defaultdict(set)
    for u, v in cur.fetchall():
        nachbarn[u].add(v)
        nachbarn[v].add(u)
    farbe = {}
    for b in sorted(knoten, key=lambda k: -len(nachbarn[k])):
        belegt = {farbe[n] for n in nachbarn[b] if n in farbe}
        farbe[b] = next(f for f in range(len(belegt) + 1) if f not in belegt)
    cur.execute("DROP TABLE IF EXISTS steiner_farbe; CREATE TABLE steiner_farbe (b bigint PRIMARY KEY, farbe int)")
    cur.executemany("INSERT INTO steiner_farbe VALUES (%s, %s)", list(farbe.items()))
    con.commit()
    print(max(farbe.values()) + 1 if farbe else 0)
    raise SystemExit
if a.farbe >= 0:
    cur.execute("SELECT b FROM steiner_farbe WHERE farbe = %s", (a.farbe,))
    in_farbe = {b for (b,) in cur.fetchall()}
    knoten = [b for b in knoten if b in in_farbe]
knoten = [b for i, b in enumerate(knoten) if i % a.teile == a.teil]
S, T = -1, -2


def loese(b, rids):
    cur.execute("""
    SELECT k.rid, g.id, g.source, g.target, g.len, g.faktor0, g.faktor1, k.zusatz_je_m, k.umweg
    FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = ANY(%s)""", (rids,))
    boegen = []                       # (rid, von, nach, kante, kosten Route, Anschluss)
    kante_c = {}                      # kante -> (len, kleinster Faktor, kleinster zusatz, kleinster umweg)
    for rid, e, s, t, l, f0, f1, z, u in cur.fetchall():
        l, z, u = float(l), float(z), float(u)
        fs = [float(f) for f in (f0, f1) if f is not None]
        if not fs:
            continue
        if f0 is not None:
            boegen.append((rid, s, t, e, l * (float(f0) + z) + u, 0.0))
        if f1 is not None:
            boegen.append((rid, t, s, e, l * (float(f1) + z) + u, 0.0))
        alt = kante_c.get(e)
        kante_c[e] = (l, min(fs), z, u) if alt is None else (l, min(alt[1], min(fs)), min(alt[2], z), min(alt[3], u))
    cur.execute("SELECT rid, id, source, target, cost FROM virt WHERE rid = ANY(%s)", (rids,))
    virt_id = {}
    for rid, vid, s, t, c in cur.fetchall():
        boegen.append((rid, s, t, None, 0.0, float(c)))
        virt_id[len(boegen) - 1] = vid
    if a.nachbar:
        # Enden am Netz der Nachbarkreuzungen: Ziel an Knoten der Routen y -> z, Start an Knoten der Routen v -> x
        # (aktueller Stand), nur Knoten im eigenen Korridor, ohne Anschlusskosten
        im_korridor = defaultdict(set)
        for rid, s, t, e, _, _ in boegen:
            if e is not None:
                im_korridor[rid].update((s, t))
        # nur Knoten auf der eigenen Seite (Ziel näher an y, Start näher an x): jede Route fährt ihre Kreuzung x -> y selbst,
        # sonst träfen sich die Wege der Nachbarkreuzungen an b und die Route schrumpfte auf null
        cur.execute("""SELECT DISTINCT r.rid, p.node FROM routen r JOIN routen n ON n.x = r.y JOIN pfad p ON p.rid = n.rid AND p.node >= 0
                       JOIN routing_graph.knoten k ON k.id = p.node
                       WHERE r.rid = ANY(%s) AND NOT n.rid = ANY(%s)
                         AND ST_Distance(k.geom, r.ziel_linie) < ST_Distance(k.geom, r.start_linie)""", (rids, rids))
        for rid, n in cur.fetchall():
            if n in im_korridor[rid]:
                boegen.append((rid, n, T, None, 0.0, 0.0))
                virt_id[len(boegen) - 1] = -(1900000000 + len(boegen))
        cur.execute("""SELECT DISTINCT r.rid, p.node FROM routen r JOIN routen v ON v.y = r.x JOIN pfad p ON p.rid = v.rid AND p.node >= 0
                       JOIN routing_graph.knoten k ON k.id = p.node
                       WHERE r.rid = ANY(%s) AND NOT v.rid = ANY(%s)
                         AND ST_Distance(k.geom, r.start_linie) < ST_Distance(k.geom, r.ziel_linie)""", (rids, rids))
        for rid, n in cur.fetchall():
            if n in im_korridor[rid]:
                boegen.append((rid, S, n, None, 0.0, 0.0))
                virt_id[len(boegen) - 1] = -(1800000000 + len(boegen))
    eids = sorted(kante_c)
    eidx = {e: i for i, e in enumerate(eids)}
    # bezahlt: Kanten im Korridor, die Routen außerhalb dieser Kreuzung benutzen (aktueller Stand)
    bezahlt = set()
    if not a.allein:
        cur.execute("""SELECT DISTINCT p.edge FROM pfad p WHERE p.edge = ANY(%s) AND p.rid <> ALL(%s)""", (eids, rids))
        bezahlt = {e for (e,) in cur.fetchall()}
    C = np.array([0.0 if e in bezahlt else kante_c[e][0] * (kante_c[e][1] + kante_c[e][2]) + kante_c[e][3] for e in eids])
    nx, nf = len(eids), len(boegen)
    c = np.concatenate([C, [a.lam * bo[4] + bo[5] for bo in boegen]])
    zeilen, spalten, werte, lo, hi = [], [], [], [], []
    r = 0
    knoten_zeile = {}
    for j, (rid, s, t, e, _, _) in enumerate(boegen):
        for n, v in ((s, 1.0), (t, -1.0)):
            key = (rid, n)
            if key not in knoten_zeile:
                knoten_zeile[key] = r
                rhs = 1.0 if n == S else (-1.0 if n == T else 0.0)
                lo.append(rhs); hi.append(rhs)
                r += 1
            zeilen.append(knoten_zeile[key]); spalten.append(nx + j); werte.append(v)
    for rid in rids:                  # Route ohne Start oder Ziel: unlösbar, Teil 2 bleibt
        if (rid, S) not in knoten_zeile or (rid, T) not in knoten_zeile:
            return None, f"ohne Start/Ziel {rid}", nx, nf, 0
    for j, bo in enumerate(boegen):
        if bo[3] is None:
            continue
        zeilen += [r, r]; spalten += [nx + j, eidx[bo[3]]]; werte += [1.0, -1.0]
        lo.append(-np.inf); hi.append(0.0)
        r += 1
    A = coo_matrix((werte, (zeilen, spalten)), shape=(r, nx + nf)).tocsr()
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=np.concatenate([np.ones(nx), np.zeros(nf)]),
               bounds=Bounds(0, 1), options={"time_limit": a.zeit, "mip_rel_gap": 1e-4})
    if res.x is None:
        return None, res.message[:60], nx, nf, len(bezahlt)
    # Wege ablesen: je Route von S den Bögen mit dem größten Fluss folgen
    aus = defaultdict(list)
    for j, bo in enumerate(boegen):
        if res.x[nx + j] > 1e-6:
            aus[(bo[0], bo[1])].append((res.x[nx + j], j))
    wege = {}
    for rid in rids:
        w, u, gesehen = [], S, set()
        while u != T:
            if u in gesehen or not aus[(rid, u)]:
                return None, f"Weg {rid} nicht ablesbar", nx, nf, len(bezahlt)
            gesehen.add(u)
            j = max(aus[(rid, u)])[1]
            w.append(j)
            u = boegen[j][2]
        wege[rid] = w
    union = {boegen[j][3] for w in wege.values() for j in w if boegen[j][3] is not None}
    return (wege, boegen, virt_id, res.fun, sum(kante_c[e][0] for e in union), C, eidx, kante_c), ("optimal" if res.status == 0 else res.message[:40]), nx, nf, len(bezahlt)


for b in knoten:
    rids = je_b[b]
    t0 = time.time()
    erg, status, nx, nf, nb = loese(b, rids)
    dt = time.time() - t0
    if erg is None:
        cur.execute("INSERT INTO steiner VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, 0, %s, %s)", (b, len(rids), nx, nf, status, dt, a.runde, nb))
        con.commit()
        continue
    wege, boegen, virt_id, ziel, union_m, C, eidx, kante_c = erg
    # Vergleich mit Teil 2 (gleiches Ziel, Wege aus pfad)
    cur.execute("SELECT rid, edge FROM pfad WHERE rid = ANY(%s) AND edge >= 0", (rids,))
    alt = defaultdict(set)
    for rid, e in cur.fetchall():
        alt[rid].add(e)
    union_alt = set().union(*alt.values())
    cur.execute("SELECT rid, sum(cost) FILTER (WHERE edge >= 0), sum(cost) FILTER (WHERE edge < 0) FROM pfad WHERE rid = ANY(%s) GROUP BY 1", (rids,))
    ziel_alt = sum(C[eidx[e]] for e in union_alt if e in eidx) + sum(a.lam * (k or 0) + (v or 0) for _, k, v in cur.fetchall())
    union_alt_m = sum(kante_c[e][0] for e in union_alt if e in kante_c)
    geaendert = 0
    zeilen = []
    for rid, w in wege.items():
        neu = [boegen[j][3] for j in w if boegen[j][3] is not None]
        if set(neu) != alt[rid]:
            geaendert += 1
        agg, seq = 0.0, 0
        for j in w:
            rid_, s, t, e, k, v = boegen[j]
            kosten = k + v
            seq += 1
            zeilen.append((rid, seq, int(s), int(e if e is not None else virt_id[j]), float(kosten), float(agg)))
            agg += kosten
        zeilen.append((rid, seq + 1, T, -1, 0.0, float(agg)))
    cur.execute("DELETE FROM pfad WHERE rid = ANY(%s)", (rids,))
    cur.executemany("INSERT INTO pfad VALUES (%s, %s, %s, %s, %s, %s)", zeilen)
    cur.execute("INSERT INTO steiner VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (b, len(rids), nx, nf, status, dt, float(ziel), float(ziel_alt), float(union_m), float(union_alt_m), geaendert, a.runde, nb))
    con.commit()
