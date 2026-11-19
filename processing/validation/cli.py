# -*- coding: utf-8 -*-
"""
Validierung der Abgabedatensätze – Kommandozeile.

Aufruf aus processing/ (oder über ./run_validation.sh, das dasselbe tut):

    python -m validation run  [--netz ren|rvn] [--clip REGION] [--output-dir DIR] [--nur B- K-]
    python -m validation list [--netz …] [--clip …]
    python -m validation show [LAUF] [--vergleich LAUF]
    python -m validation diff [BASIS] [VERGLEICH] [--check ID] [--alle] [--limit N]
    python -m validation history [-n 10] [--netz …] [--clip …]

LAUF ist eine Nummer aus `list` (7 oder #7), relativ (-1 = neuester, -2 = davor)
oder ein Ordnername unter validation/runs/. `diff` ohne Läufe fragt interaktiv.

Exit-Code von `run`: 1, wenn eine Prüfung mit Schwere „fehler“ Verstöße hat oder
eine Prüfung nicht laufen konnte; Warnungen ändern ihn nicht.
"""

import argparse
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

from . import report, store
from .datasets import PROCESSING_DIR, Kontext, git_stand
from .framework import ERROR, FAIL, REGISTRY, ausfuehren
from . import checks  # noqa: F401  – registriert alle Prüfungen

KOMMANDOS = ("run", "list", "show", "diff", "history")
REGIONEN = ("neukoelln", "norden", "sueden")


def _ruhig():
    """Die Prüfungen sollen nur über das Ergebnis berichten, nicht über Logs der Hilfsmodule."""
    logging.getLogger().setLevel(logging.WARNING)
    warnings.filterwarnings("ignore")


def cmd_run(args):
    _ruhig()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (PROCESSING_DIR / output_dir).resolve()
    ctx = Kontext(netz=args.netz, clip=args.clip, output_dir=output_dir)
    start = datetime.now()

    tty = sys.stderr.isatty()

    def fortschritt(check):
        if tty:
            sys.stderr.write(f"\r\033[KPrüfe {check.id} …")
            sys.stderr.flush()

    ergebnisse = ausfuehren(ctx, auswahl=args.nur, fortschritt=fortschritt)
    if tty:
        sys.stderr.write("\r\033[K")
    if not ergebnisse:
        raise SystemExit(f"Keine Prüfung passt zu --nur {' '.join(args.nur)}")

    try:
        output_rel = str(output_dir.relative_to(PROCESSING_DIR))
    except ValueError:
        output_rel = str(output_dir)
    meta = {
        "zeit": start.isoformat(timespec="seconds"),
        "dauer_s": round((datetime.now() - start).total_seconds(), 1),
        "netz": args.netz,
        "clip": args.clip,
        "output_dir": output_rel,
        "auswahl": args.nur,
        "git": git_stand(),
        "eingaben": ctx.eingaben,
    }
    lauf = store.speichern(meta, ergebnisse)
    zaehler = report.uebersicht(lauf, store.vorgaenger(lauf))
    print(report.grau("Vergleich mit einem beliebigen Lauf: ./run_validation.sh diff"))
    return 1 if zaehler[FAIL] or zaehler[ERROR] else 0


def _gefiltert(args):
    laeufe = store.alle_laeufe()
    if getattr(args, "netz", None):
        laeufe = [l for l in laeufe if l.meta["netz"] == args.netz]
    if getattr(args, "clip", None):
        laeufe = [l for l in laeufe if l.meta.get("clip") == (None if args.clip == "-" else args.clip)]
    return laeufe


def cmd_list(args):
    laeufe = _gefiltert(args)
    if not laeufe:
        print("Keine gespeicherten Läufe.")
        return 0
    report.liste(laeufe[-args.n:] if args.n else laeufe)
    return 0


def cmd_show(args):
    lauf = store.finde(args.lauf)
    vergleich = store.finde(args.vergleich) if args.vergleich else store.vorgaenger(lauf)
    report.uebersicht(lauf, vergleich)
    return 0


def _frage(text, standard):
    try:
        antwort = input(f"{text} [{standard}]: ").strip()
    except EOFError:
        antwort = ""
    return antwort or standard


def _check_id(eingabe, ids):
    eingabe = eingabe.strip().upper()
    if eingabe in ids:
        return eingabe
    treffer = [i for i in ids if i.upper().startswith(eingabe)]
    return treffer[0] if len(treffer) == 1 else None


def cmd_diff(args):
    laeufe = store.alle_laeufe()
    if len(laeufe) < 2:
        raise SystemExit("Für einen Vergleich braucht es mindestens zwei gespeicherte Läufe.")
    interaktiv = args.basis is None and sys.stdin.isatty()

    if args.basis is None:
        b = store.finde(args.vergleich or -1, laeufe)
        vor = store.vorgaenger(b) or laeufe[-2]
        if interaktiv:
            report.liste(laeufe[-20:])
            print()
            b = store.finde(_frage("Vergleichslauf", b.nr), laeufe)
            vor = store.vorgaenger(b) or vor
            a = store.finde(_frage("Basislauf", vor.nr), laeufe)
            print()
        else:
            a = vor
    else:
        a = store.finde(args.basis, laeufe)
        b = store.finde(args.vergleich or -1, laeufe)

    if args.check:
        cid = _check_id(args.check, set(a.ergebnisse) | set(b.ergebnisse))
        if not cid:
            raise SystemExit(f"Prüfung „{args.check}“ nicht gefunden.")
        report.diff_details(a, b, cid, args.limit)
        return 0

    geaendert = report.diff(a, b, alle=args.alle)
    while interaktiv and geaendert:
        print()
        try:
            eingabe = input("Neue/behobene Verstöße einer Prüfung zeigen (ID, Enter = Ende): ").strip()
        except EOFError:
            break
        if not eingabe:
            break
        cid = _check_id(eingabe, set(a.ergebnisse) | set(b.ergebnisse))
        if cid:
            report.diff_details(a, b, cid, args.limit)
        else:
            print(f"Unbekannte Prüfung: {eingabe}")
    return 0


def cmd_history(args):
    laeufe = store.alle_laeufe()
    if not laeufe:
        print("Keine gespeicherten Läufe.")
        return 0
    if not args.netz and not args.clip:
        variante = laeufe[-1].variante  # Standard: Variante des neuesten Laufs
        laeufe = [l for l in laeufe if l.variante == variante]
        print(report.grau(f"netz={variante[0]} clip={variante[1] or '–'} (andere mit --netz/--clip)"))
    else:
        laeufe = _gefiltert(args)
    report.verlauf(laeufe[-args.n:])
    return 0


def parser():
    p = argparse.ArgumentParser(prog="validation", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="kommando", required=True)

    r = sub.add_parser("run", help="alle Prüfungen ausführen und den Lauf speichern")
    r.add_argument("--netz", choices=("ren", "rvn"), default="ren", help="Zielnetz (Standard: ren)")
    r.add_argument("--clip", choices=REGIONEN, help="regionaler Zuschnitt")
    r.add_argument("--output-dir", default="output",
                   help="Ordner mit den Abgabedateien, relativ zu processing/ (Standard: output)")
    r.add_argument("--nur", nargs="+", metavar="PRÄFIX",
                   help=f"nur Prüfungen, deren ID so beginnt (z. B. B- VK-). Vorhanden: {', '.join(sorted(REGISTRY))}")
    r.set_defaults(fn=cmd_run)

    for name, fn, hilfe in [("list", cmd_list, "gespeicherte Läufe auflisten"),
                            ("history", cmd_history, "Anzahl Verstöße je Prüfung über die letzten Läufe")]:
        s = sub.add_parser(name, help=hilfe)
        s.add_argument("--netz", choices=("ren", "rvn"))
        s.add_argument("--clip", choices=REGIONEN + ("-",), help="Zuschnitt; - = vollständiger Datensatz")
        s.add_argument("-n", type=int, default=0 if name == "list" else 10, help="nur die letzten n Läufe")
        s.set_defaults(fn=fn)

    s = sub.add_parser("show", help="Übersicht eines gespeicherten Laufs")
    s.add_argument("lauf", nargs="?", default="-1")
    s.add_argument("--vergleich", help="Lauf für die Spalte „Veränderung“ (Standard: vorheriger derselben Variante)")
    s.set_defaults(fn=cmd_show)

    d = sub.add_parser("diff", help="zwei beliebige Läufe direkt vergleichen")
    d.add_argument("basis", nargs="?", help="älterer Lauf; ohne Angabe interaktiv")
    d.add_argument("vergleich", nargs="?", help="neuerer Lauf (Standard: neuester)")
    d.add_argument("--check", help="nur neue und behobene Verstöße dieser Prüfung zeigen")
    d.add_argument("--alle", action="store_true", help="auch unveränderte Prüfungen zeigen")
    d.add_argument("--limit", type=int, default=20, help="Anzahl Objekte je Liste, 0 = alle (Standard: 20)")
    d.set_defaults(fn=cmd_diff)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in KOMMANDOS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "run")
    args = parser().parse_args(argv)
    return args.fn(args)
