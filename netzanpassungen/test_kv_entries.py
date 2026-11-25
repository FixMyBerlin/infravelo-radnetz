#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for kv_entries.py with a fake HTTP layer (no network).

    .venv/bin/python netzanpassungen/test_kv_entries.py
"""

import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

import kv_entries  # noqa: E402

ENV = {"VITE_KV_BASE_URL": "https://kv.example.org/", "VITE_KV_PROJECT": "netzanpassungen",
       "VITE_KV_API_KEY": "test-key"}


class FakeKv:
    """Answers like the KV API: pages of `items` with `next_cursor`, filtered by tag."""

    def __init__(self, items, page_size):
        self.items = items
        self.page_size = page_size
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        tagged = [item for item in self.items if query["tag"] in item["tags"]]
        start = int(query.get("cursor", 0))
        end = start + int(query["limit"])
        return {"items": tagged[start:end], "next_cursor": str(end) if end < len(tagged) else None}


def entry(index, gebiet="berlin", kind="edge_correction"):
    return {"id": f"{gebiet}:x:{index}", "data": {"kind": kind}, "tags": [gebiet, "x"],
            "created_by": "a", "updated_by": "a", "created_at": "2026-11-19T10:00:00Z", "updated_at": "2026-11-19T10:00:00Z"}


class KvEntriesTest(unittest.TestCase):
    def test_paginates_until_no_cursor(self):
        items = [entry(i) for i in range(7)] + [entry(9, gebiet="neukoelln")]
        fake = FakeKv(items, page_size=3)
        result = kv_entries.fetch_entries("berlin", env=ENV, get_json=fake, page_size=3)
        self.assertEqual([e["id"] for e in result["entries"]], [f"berlin:x:{i}" for i in range(7)])
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(result["gebiet"], "berlin")
        self.assertTrue(result["exported_at"])

    def test_url_and_headers(self):
        fake = FakeKv([entry(1)], page_size=500)
        kv_entries.fetch_entries("berlin", env=ENV, get_json=fake)
        url, headers = fake.calls[0]
        self.assertTrue(url.startswith("https://kv.example.org/v1/projects/netzanpassungen/entries?"))
        self.assertIn("tag=berlin", url)
        self.assertNotIn("cursor=", url)
        self.assertEqual(headers["X-Api-Key"], "test-key")
        self.assertEqual(headers["Origin"], "http://127.0.0.1:33480")

    def test_second_page_sends_cursor(self):
        fake = FakeKv([entry(i) for i in range(4)], page_size=2)
        kv_entries.fetch_entries("berlin", env=ENV, get_json=fake, page_size=2)
        self.assertIn("cursor=2", fake.calls[1][0])

    def test_reads_the_entries_of_every_kind_tag_of_the_area(self):
        def tagged(index, kind, tag):
            return {**entry(index, kind=kind), "id": f"berlin:{tag}:{index}", "tags": ["berlin", tag]}
        items = [tagged(1, "route_check", "routenpruefung"), tagged(2, "bridge_check", "bauwerk"),
                 {**tagged(3, "bridge_check", "bauwerk"), "tags": ["neukoelln", "bauwerk"]}]
        result = kv_entries.fetch_entries("berlin", env=ENV, get_json=FakeKv(items, 500))
        self.assertEqual([(e["id"], e["data"]["kind"]) for e in result["entries"]],
                         [("berlin:routenpruefung:1", "route_check"), ("berlin:bauwerk:2", "bridge_check")])

    def test_empty_area(self):
        result = kv_entries.fetch_entries("leer", env=ENV, get_json=FakeKv([entry(1)], 500))
        self.assertEqual(result["entries"], [])

    def test_env_missing_value_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("VITE_KV_BASE_URL=https://kv.example.org\nVITE_KV_PROJECT=netzanpassungen\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                kv_entries.read_env(path)
            self.assertIn("VITE_KV_API_KEY", str(raised.exception))

    def test_env_reads_quoted_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("# comment\nVITE_KV_BASE_URL='https://kv.example.org'\nVITE_KV_PROJECT=\"p\"\n"
                            "VITE_KV_API_KEY=k\nOTHER=1\n", encoding="utf-8")
            self.assertEqual(kv_entries.read_env(path),
                             {"VITE_KV_BASE_URL": "https://kv.example.org", "VITE_KV_PROJECT": "p", "VITE_KV_API_KEY": "k"})


if __name__ == "__main__":
    unittest.main()
