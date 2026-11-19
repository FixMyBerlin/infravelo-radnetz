# -*- coding: utf-8 -*-
"""
report.py
--------------------------------------------------------------------
Ausgabe im Terminal: Übersicht eines Laufs, Diff zweier Läufe, Liste und Verlauf.

Bestandene Prüfungen bekommen eine Zeile, Details erscheinen nur bei Verstößen.
"""

import os
import sys
from collections import Counter

from .datasets import DATENSAETZE
from .framework import ERROR, FAIL, OK, WARN

_FARBE = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _FARBE else text


def rot(t): return _c("31", t)
def gruen(t): return _c("32", t)
def gelb(t): return _c("33", t)
def grau(t): return _c("90", t)
def fett(t): return _c("1", t)


SYMBOL = {OK: gruen("✓"), FAIL: rot("✗"), WARN: gelb("⚠"), ERROR: rot("!")}
STATUS_TEXT = {OK: "ok", FAIL: "fehlgeschlagen", WARN: "Warnung", ERROR: "nicht gelaufen"}
BEISPIELE = 5
DETAIL_GRUPPEN = 8


def zahl(n):
    return f"{n:,}".replace(",", ".")


def _kurz(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


def lauf_kopf(lauf):
    m = lauf.meta
    git = m.get("git") or {}
    commit = (git.get("commit") or "?") + ("+lokal geändert" if git.get("dirty") else "")
    clip = m.get("clip") or "–"
    return (f"#{lauf.nr}  {lauf.zeit:%d.%m.%Y %H:%M}  netz={m['netz']}  clip={clip}  "
            f"output={m.get('output_dir', 'output')}  commit {commit}")


def _veraenderung(neu, behoben):
    if not neu and not behoben:
        return grau("=")
    teile = []
    if neu:
        teile.append(rot(f"+{zahl(neu)}"))
    if behoben:
        teile.append(gruen(f"−{zahl(behoben)}"))
    return " ".join(teile)


def _objekte(e):
    return e.get("objekte", e["anzahl"])  # Läufe vor Einführung von „objekte“


def _anteil(e):
    if not e["geprueft"] or not e["anzahl"]:
        return ""
    p = 100 * _objekte(e) / e["geprueft"]
    return f"{p:.1f} %".replace(".", ",") if p >= 0.1 else "<0,1 %"


def uebersicht(lauf, vergleich=None):
    """Übersicht gruppiert nach Datensatz, danach Details der nicht bestandenen Prüfungen."""
    print(fett(f"Validierung {lauf_kopf(lauf)}"))
    if vergleich:
        print(grau(f"Veränderung gegenüber #{vergleich.nr} vom {vergleich.zeit:%d.%m.%Y %H:%M} "
                   f"(+ neue Verstöße, − behobene)"))
    ergebnisse = lauf.meta["ergebnisse"]
    alt = vergleich.ergebnisse if vergleich else {}
    eingaben = lauf.meta.get("eingaben", {})

    for ds, titel in DATENSAETZE.items():
        gruppe = [e for e in ergebnisse if e["datensatz"] == ds]
        if not gruppe:
            continue
        objekte = eingaben.get(ds, {}).get("objekte")
        print()
        print(fett(f"{ds}  {titel}") + (grau(f"  ({zahl(objekte)} Objekte)") if objekte is not None else ""))
        print(grau(f"  {'':<2}{'':<23}{'':<46} {'Verstöße':>8}  {'Objekte betroffen':>17}"))
        for e in gruppe:
            zeile = f"  {SYMBOL[e['status']]} {e['id']:<22} {_kurz(e['name'], 46):<46}"
            if e["status"] == ERROR:
                print(zeile + rot("  nicht gelaufen"))
                continue
            zeile += f" {zahl(e['anzahl']):>8}  {zahl(_objekte(e)):>7} / {zahl(e['geprueft']):<7} {_anteil(e):>7}"
            if vergleich:
                if e["id"] in alt and alt[e["id"]]["status"] != ERROR:
                    a, b = vergleich.verstoesse(e["id"]), lauf.verstoesse(e["id"])
                    zeile += "   " + _veraenderung(len(b - a), len(a - b))
                else:
                    zeile += "   " + grau("neu")
            print(zeile)

    probleme = [e for e in ergebnisse if e["status"] in (FAIL, WARN)]
    nicht_gelaufen = {}
    for e in ergebnisse:
        if e["status"] == ERROR:
            nicht_gelaufen.setdefault(e["meldung"], []).append(e["id"])
    if probleme or nicht_gelaufen:
        print()
        print(fett("Details"))
    for meldung, ids in nicht_gelaufen.items():
        print()
        print(f"{SYMBOL[ERROR]} {fett(', '.join(ids))}  " + grau("(nicht gelaufen)"))
        print(rot(f"   {meldung}"))
    for e in probleme:
        print()
        print(f"{SYMBOL[e['status']]} {fett(e['id'])}  {e['name']}  " + grau(f"({STATUS_TEXT[e['status']]})"))
        print(grau(f"   Regel: {e['regel']}"))
        paare = sorted(lauf.verstoesse(e["id"]))
        details = Counter(d for _, d in paare)
        if len(details) > 1 or (details and next(iter(details)) not in ("", "fehlt")):
            haeufig = details.most_common(DETAIL_GRUPPEN)
            rest = len(details) - len(haeufig)
            print("   Nach Detail: " + " · ".join(f"{d} {zahl(n)}" for d, n in haeufig)
                  + (grau(f" · … {rest} weitere") if rest > 0 else ""))
        objekte = list(dict.fromkeys(o for o, _ in paare))
        mehr = len(objekte) - BEISPIELE
        print("   Beispiele: " + ", ".join(objekte[:BEISPIELE]) + (grau(f" (+{zahl(mehr)})") if mehr > 0 else ""))

    zaehler = Counter(e["status"] for e in ergebnisse)
    print()
    print(fett("Ergebnis: ") + " · ".join([
        gruen(f"{zaehler[OK]} bestanden"),
        (rot if zaehler[FAIL] else grau)(f"{zaehler[FAIL]} fehlgeschlagen"),
        (gelb if zaehler[WARN] else grau)(f"{zaehler[WARN]} Warnungen"),
        (rot if zaehler[ERROR] else grau)(f"{zaehler[ERROR]} nicht gelaufen"),
    ]))
    print(grau(f"Gespeichert: {lauf.ordner}"))
    return zaehler


def _eingaben_vergleich(a, b):
    ea, eb = a.meta.get("eingaben", {}), b.meta.get("eingaben", {})
    teile = []
    for name in sorted(set(ea) | set(eb)):
        x, y = ea.get(name), eb.get(name)
        if not x or not y:
            teile.append(f"{name} {'neu' if y else 'entfallen'}")
        elif x["sha256"] == y["sha256"]:
            teile.append(grau(f"{name} unverändert"))
        else:
            n = ""
            if x.get("objekte") is not None and y.get("objekte") is not None:
                n = f" ({zahl(x['objekte'])} → {zahl(y['objekte'])} Objekte)"
            teile.append(gelb(f"{name} geändert{n}"))
    return teile


def diff(a, b, alle=False):
    """Vergleicht zwei Läufe direkt miteinander; Läufe dazwischen spielen keine Rolle.

    Gibt die IDs der Prüfungen zurück, die sich verändert haben.
    """
    print(fett("Vergleich"))
    print(f"  Basis      {lauf_kopf(a)}")
    print(f"  Vergleich  {lauf_kopf(b)}")
    if a.variante != b.variante:
        print(gelb("  Achtung: unterschiedliches Netz oder Zuschnitt, Anzahlen sind nur bedingt vergleichbar."))
    print("  Eingaben:  " + ", ".join(_eingaben_vergleich(a, b)))
    print()

    ea, eb = a.ergebnisse, b.ergebnisse
    kopf = f"    {'Prüfung':<22} {'Name':<40} {'Basis':>8} {'Vergl.':>8} {'Δ':>7} {'neu':>7} {'behoben':>8}"
    print(grau(kopf))
    geaendert, gleich = [], 0
    for cid in sorted(set(ea) | set(eb)):
        x, y = ea.get(cid), eb.get(cid)
        name = _kurz((y or x)["name"], 40)
        if not x or not y or ERROR in (x["status"], y["status"]):
            sa = STATUS_TEXT[x["status"]] if x else "fehlt"
            sb = STATUS_TEXT[y["status"]] if y else "fehlt"
            if sa != sb or alle:
                print(f"  {SYMBOL[y['status']] if y else ' '} {cid:<22} {name:<40} {sa:>8} → {sb}")
                geaendert.append(cid)
            else:
                gleich += 1
            continue
        va, vb = a.verstoesse(cid), b.verstoesse(cid)
        neu, behoben = len(vb - va), len(va - vb)
        status_wechsel = x["status"] != y["status"]
        if not (neu or behoben or status_wechsel or alle):
            gleich += 1
            continue
        delta = y["anzahl"] - x["anzahl"]
        d_text = (rot if delta > 0 else gruen if delta < 0 else grau)(f"{delta:+,}".replace(",", ".").rjust(7))
        wechsel = f"  {SYMBOL[x['status']]}→{SYMBOL[y['status']]}" if status_wechsel else ""
        print(f"  {SYMBOL[y['status']]} {cid:<22} {name:<40} {zahl(x['anzahl']):>8} {zahl(y['anzahl']):>8} "
              f"{d_text} {(rot if neu else grau)(zahl(neu).rjust(7))} {(gruen if behoben else grau)(zahl(behoben).rjust(8))}"
              f"{wechsel}")
        if neu or behoben or status_wechsel:
            geaendert.append(cid)
    if not geaendert:
        print(gruen("  Keine Veränderung: alle Prüfungen haben dieselben Verstöße."))
    if gleich and not alle:
        print(grau(f"  {gleich} Prüfungen unverändert (--alle zeigt sie)"))
    return geaendert


def diff_details(a, b, cid, limit=20):
    """Neue und behobene Verstöße einer Prüfung zwischen zwei Läufen."""
    va, vb = a.verstoesse(cid), b.verstoesse(cid)
    for titel, menge, farbe in [("Neu", vb - va, rot), ("Behoben", va - vb, gruen)]:
        print()
        print(farbe(fett(f"{titel} in {cid}: {zahl(len(menge))}")))
        for objekt, detail in sorted(menge)[: limit or None]:
            print(f"  {objekt}" + (grau(f"  {detail}") if detail else ""))
        if limit and len(menge) > limit:
            print(grau(f"  … {zahl(len(menge) - limit)} weitere (--limit 0 zeigt alle)"))


def liste(laeufe):
    print(grau(f"  {'Nr':>4}  {'Zeit':<16}  {'Netz':<4}  {'Clip':<10}  {'Commit':<14}  Ergebnis"))
    for l in laeufe:
        z = Counter(e["status"] for e in l.meta["ergebnisse"])
        git = l.meta.get("git") or {}
        commit = (git.get("commit") or "?") + ("+" if git.get("dirty") else "")
        ergebnis = " ".join(x for x in [
            gruen(f"{z[OK]}✓"),
            rot(f"{z[FAIL]}✗") if z[FAIL] else "",
            gelb(f"{z[WARN]}⚠") if z[WARN] else "",
            rot(f"{z[ERROR]}!") if z[ERROR] else "",
        ] if x)
        print(f"  {'#' + str(l.nr):>4}  {l.zeit:%d.%m.%Y %H:%M}  {l.meta['netz']:<4}  "
              f"{l.meta.get('clip') or '–':<10}  {commit:<14}  {ergebnis}")


def verlauf(laeufe):
    """Anzahl Verstöße je Prüfung über mehrere Läufe; Veränderungen zum linken Nachbarn sind markiert."""
    ids = sorted({cid for l in laeufe for cid in l.ergebnisse})
    print(grau(f"  {'Prüfung':<22}" + "".join(f"{'#' + str(l.nr):>9}" for l in laeufe)))
    print(grau(f"  {'':<22}" + "".join(f"{l.zeit:%d.%m.}".rjust(9) for l in laeufe)))
    for cid in ids:
        zeile, vorher = f"  {cid:<22}", None
        for l in laeufe:
            e = l.ergebnisse.get(cid)
            if not e:
                text, wert = "–", None
            elif e["status"] == ERROR:
                text, wert = "!", None
            else:
                text, wert = zahl(e["anzahl"]), e["anzahl"]
            zelle = text.rjust(9)
            if wert is not None and vorher is not None and wert != vorher:
                zelle = (rot if wert > vorher else gruen)(zelle)
            elif e and e["status"] == OK:
                zelle = grau(zelle)
            zeile += zelle
            vorher = wert
        print(zeile)
