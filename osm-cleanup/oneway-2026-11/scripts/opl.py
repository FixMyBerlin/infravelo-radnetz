"""Minimal OPL reader for ways (osmium cat -f opl), keeps metadata, tags and node refs."""

import re

_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def _unescape(s):
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def _parse_tags(s):
    tags = {}
    if not s:
        return tags
    for kv in s.split(","):
        k, _, v = kv.partition("=")
        tags[_unescape(k)] = _unescape(v)
    return tags


def read_ways(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("w"):
                continue
            way = {"tags": {}, "nodes": []}
            for field in line.rstrip("\n").split(" "):
                if not field:
                    continue
                c, rest = field[0], field[1:]
                if c == "w":
                    way["id"] = int(rest)
                elif c == "v":
                    way["version"] = int(rest)
                elif c == "c":
                    way["changeset"] = int(rest)
                elif c == "t":
                    way["timestamp"] = rest
                elif c == "i":
                    way["uid"] = int(rest) if rest else 0
                elif c == "u":
                    way["user"] = _unescape(rest)
                elif c == "T":
                    way["tags"] = _parse_tags(rest)
                elif c == "N":
                    way["nodes"] = [int(n[1:]) for n in rest.split(",") if n]
            yield way


def is_fmc(user):
    return (user or "").lower().startswith("fmc")
