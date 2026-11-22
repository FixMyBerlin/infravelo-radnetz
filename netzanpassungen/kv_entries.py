#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kv_entries.py
--------------------------------------------------------------------
Reads all entries of one area (Gebiet) of the Netzanpassungen app directly from its KV database,
read-only. Step 3 (apply_app_result.py) uses it by default instead of a manual export.

    GET {VITE_KV_BASE_URL}/v1/projects/{VITE_KV_PROJECT}/entries?tag={gebiet}&limit=…&cursor=…
    headers X-Api-Key: {VITE_KV_API_KEY}, Origin: http://127.0.0.1:33480

The Origin is one the API allows (without it the API answers 403 origin_not_allowed). Reading needs no
OSM login. The answer is `{items: [{id, data, tags, created_by, updated_by, created_at, updated_at, …}],
next_cursor}`; pages are read until next_cursor is empty.

The three values come from the .env in the repo root (same names as in the app, see .env.example).

Every entry carries the area tag next to the tag of its kind (`korrektur`, `zuordnung`, `routenpruefung`, `bauwerk`, …), so
one read by area returns all kinds, the checks of the app included: `route_check` (tag `routenpruefung`) and `bridge_check`
(tag `bauwerk`, KV id `{gebiet}:bauwerk:bw-<node id>`). Step 3 picks the kinds it needs by `data.kind`; `route_check` is ignored
by steps 1 and 3, `bridge_check` by step 1 and applied by step 3.

Result: the same shape as the app export „Alle Einträge“ (`{gebiet, exported_at, entries}`), so step 3
treats both alike.

    .venv/bin/python netzanpassungen/kv_entries.py berlin            # count the entries by kind
    .venv/bin/python netzanpassungen/kv_entries.py berlin --out x.json  # save them like the app export
"""

import argparse
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_KEYS = ("VITE_KV_BASE_URL", "VITE_KV_PROJECT", "VITE_KV_API_KEY")
ORIGIN = "http://127.0.0.1:33480"
# Cloudflare in front of the KV API blocks the default Python-urllib signature (error 1010)
USER_AGENT = "infravelo-radnetz-pipeline/1.0"
PAGE_SIZE = 500
MAX_PAGES = 1000  # safety stop against a cursor that never ends
TIMEOUT_S = 60


def read_env(path=ENV_PATH):
    """The KV settings from .env; stops with a clear message if one is missing."""
    values = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    missing = [key for key in ENV_KEYS if not values.get(key)]
    if missing:
        raise SystemExit(f"{', '.join(missing)} missing in {path}. Copy them from the .env of the Netzanpassungen "
                         "app (infravelo-apps/netzanpassungen/.env), see .env.example; or pass --export <file>.")
    return {key: values[key] for key in ENV_KEYS}


def http_get_json(url, headers):
    """GET a JSON document (the real HTTP layer; tests pass their own)."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:300]
        raise SystemExit(f"KV database answered {error.code} for {url.split('?')[0]}: {body}") from error


def fetch_entries(gebiet, env=None, get_json=http_get_json, page_size=PAGE_SIZE):
    """All entries tagged with `gebiet`, page by page. Returns {gebiet, exported_at, entries}."""
    env = env or read_env()
    base = env["VITE_KV_BASE_URL"].rstrip("/")
    project = urllib.parse.quote(env["VITE_KV_PROJECT"], safe="")
    headers = {"X-Api-Key": env["VITE_KV_API_KEY"], "Origin": ORIGIN, "Accept": "application/json",
               "User-Agent": USER_AGENT}
    entries, cursor = [], None
    for _ in range(MAX_PAGES):
        query = {"tag": gebiet, "limit": page_size}
        if cursor:
            query["cursor"] = cursor
        page = get_json(f"{base}/v1/projects/{project}/entries?{urllib.parse.urlencode(query)}", headers)
        entries.extend(page.get("items") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            break
    else:
        raise SystemExit(f"KV database: more than {MAX_PAGES} pages for {gebiet}, stopped")
    exported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    logging.info(f"KV database {env['VITE_KV_PROJECT']}, area {gebiet}: {len(entries)} entries")
    return {"gebiet": gebiet, "exported_at": exported_at, "entries": entries}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gebiet", help="area tag in the app, e.g. berlin")
    parser.add_argument("--out", type=Path, help="write the entries like the app export „Alle Einträge“")
    args = parser.parse_args()
    export = fetch_entries(args.gebiet)
    kinds = Counter((entry.get("data") or {}).get("kind", "?") for entry in export["entries"])
    logging.info(f"By kind: {dict(sorted(kinds.items()))}")
    if args.out:
        args.out.write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
        logging.info(f"Written: {args.out}")


if __name__ == "__main__":
    main()
