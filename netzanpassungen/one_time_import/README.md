# One-time import into the Netzanpassungen app

This folder holds old lists that went **once** into the Netzanpassungen app (KV database) and are an archive afterwards. The pipeline does not read this folder (only a few tests and old ids, see below). Manual work lives in the app; `apply_app_result.py` writes everything the pipeline needs from it to `netzanpassungen/output/`.

Principle: after the one-time takeover only the data of the app count; old lists are an archive. Nothing changes here afterwards; whoever needs a correction makes it in the app.

Two takeovers happened:

- the old override lists of edges, converted on 2026-11-11 into `altlisten_korrekturen.json` and uploaded in the "Gebiet" step of the app with "Einträge einspielen" (area Berlin);
- the 53 virtual nodes of 2025, taken over by the app itself (see the last section).

| File | Content | Origin |
|---|---|---|
| `altlisten_korrekturen.json` | 38 `edge_correction` entries (`von_nutzer: "Altliste"`): `verkehrsrichtung` from `rvn_korrekturen.csv` (18) and `opposite_edge_overwrite_element_nr.txt` (1, mode `remove`, only Detailnetz B to R), plus 19 exclusions from `ausschluss_element_nr.csv` (Tunnel Tiergarten, motorway feeders). `kommentar` is the reason given in the list | The three lists in [`2025/`](./2025/), converted with a one-time script (not in the repo) |
| `2025/Virtuelle-Knotenpunkte.gpkg` | the 53 virtual nodes of 2025 (numbers `0001`–`0053`), see [below](#the-53-virtual-nodes-of-2025) | Delivery 2025, moved here from `data/` on 2026-11-19 |

## `2025/`: the old override lists (archive)

The three manual lists of 2025, kept unchanged as an archive. In 2026 they were converted into `altlisten_korrekturen.json` and taken into the app; for REN+ the app is the only place for such corrections now, and nobody adds entries here.

| File | Before 2026-11 in | Still read by |
|---|---|---|
| `rvn_korrekturen.csv` | `data/` | `processing/scripts/enrich_rvn_with_detailnetz.py --netz rvn` (direction corrections of the RVN) |
| `opposite_edge_overwrite_element_nr.txt` | `data/` | the evaluation of `processing/map-matching` (`manual_element_lists` in `config/default.toml`, only to mark deviations; the matching does not use it). Node ids translated to the four-digit numbers on 2026-11-12 (`data/VIRTUELLE-KNOTENPUNKTE.md`) |
| `ausschluss_element_nr.csv` | `ren-network/` | nothing (archive only) |

The RVN processing reads the first two until the customer delivery on the Radvorrangnetz (RVN) is done; behaviour unchanged, only the path moved. After that delivery they are archive only.

## The 53 virtual nodes of 2025

`2025/Virtuelle-Knotenpunkte.gpkg` (layer `Virtuelle-Knotenpunkte`, numbers `0001`–`0053` in `Knotenpunkt-ID`, the 2025 id in `id_rvn_2025`, EPSG:25833) is the delivery of 2025, kept unchanged as an archive. Until 2026-11-19 it was a frozen input of the pipeline in `data/`.

The Netzanpassungen app took the 53 over **once, by itself**: when a logged-in user opens the area `berlin`, it writes them as `virtual_node` entries (`herkunft: rvn_2025`, `nummer`, `id_rvn_2025`, fixed entry ids `rvn2025-0001` … `rvn2025-0053`). A number that an entry already carries is skipped, so once all are there nothing more is written (code: infravelo-apps `netzanpassungen/src/network/take-over-2025.ts`). From then on the entries are the only source: they can be moved or deleted in the app like any other node, and a deleted one keeps its number (`status = geloescht`).

The pipeline reads them from the KV database, not from this file: `read_registry()` in `data/virtuelle_knotenpunkte.py` needs `VITE_KV_*` in `.env` (like step 3) and stops with a clear message if not all 53 are there (then open the area `berlin` once in the app while logged in). Step 1 (`ren-network/merge_networks.py`) splits REN+ at the active ones, step 3 takes their rows from the entries. The file is only read by tests and by `old_to_new()` (old id `V…` to number).

Where all virtual nodes end up: `apply_app_result.py` writes the 53 and every numbered node of the app to `netzanpassungen/output/virtuelle_knoten.gpkg`. `processing/` and `knotenpunkte/` read that file through `read_active()` of `data/virtuelle_knotenpunkte.py`. If it is missing, the scripts stop and say that step 3 has to run first.
