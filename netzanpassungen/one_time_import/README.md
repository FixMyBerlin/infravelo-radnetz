# One-time import into the Netzanpassungen app

This folder holds a file that is uploaded **once** into the Netzanpassungen app (KV database) and is an archive afterwards. The pipeline never reads this folder. Manual work lives in the app; `apply_app_result.py` writes everything the pipeline needs from it to `netzanpassungen/output/`.

Converted on 2026-11-11 from the old override lists. It is uploaded in the "Gebiet" step of the app with "Einträge einspielen" (area Berlin). Nothing changes here afterwards; whoever needs a correction makes it in the app.

| File | Content | Origin |
|---|---|---|
| `altlisten_korrekturen.json` | 38 `edge_correction` entries (`von_nutzer: "Altliste"`): `verkehrsrichtung` from `rvn_korrekturen.csv` (18) and `opposite_edge_overwrite_element_nr.txt` (1, mode `remove`, only Detailnetz B to R), plus 19 exclusions from `ausschluss_element_nr.csv` (Tunnel Tiergarten, motorway feeders). `kommentar` is the reason given in the list | The three lists in [`2025/`](./2025/), converted with a one-time script (not in the repo) |

## `2025/`: the old override lists (archive)

The three manual lists of 2025, kept unchanged as an archive. In 2026 they were converted into `altlisten_korrekturen.json` and taken into the app; for REN+ the app is the only place for such corrections now, and nobody adds entries here.

| File | Before 2026-11 in | Still read by |
|---|---|---|
| `rvn_korrekturen.csv` | `data/` | `processing/scripts/enrich_rvn_with_detailnetz.py --netz rvn` (direction corrections of the RVN) |
| `opposite_edge_overwrite_element_nr.txt` | `data/` | the evaluation of `processing/map-matching` (`manual_element_lists` in `config/default.toml`, only to mark deviations; the matching does not use it). Node ids translated to the four-digit numbers on 2026-11-12 (`data/VIRTUELLE-KNOTENPUNKTE.md`) |
| `ausschluss_element_nr.csv` | `ren-network/` | nothing (archive only) |

The RVN processing reads the first two until the customer delivery on the Radvorrangnetz (RVN) is done; behaviour unchanged, only the path moved. After that delivery they are archive only.

## The 53 virtual nodes of 2025 are not in this folder

They were delivered in 2025, so they are **not** imported into the app. They are a frozen, read-only input of the pipeline (like the Detailnetz nodes): [`data/Virtuelle-Knotenpunkte.gpkg`](../../data/Virtuelle-Knotenpunkte.gpkg) (layer `Virtuelle-Knotenpunkte`, numbers `0001`–`0053` in `Knotenpunkt-ID`, the 2025 id in `id_rvn_2025`, EPSG:25833). `ren-network/merge_networks.py` splits the REN+ edges at them; they reach the app as `knoten` with `ist_virtuell = 1` and `id_rvn_2025` in the app input.

Where all virtual nodes end up: `apply_app_result.py` writes the 53 and every numbered node of the app to `netzanpassungen/output/virtuelle_knoten.gpkg`. `processing/` and `knotenpunkte/` read that file through `read_active()` of `data/virtuelle_knotenpunkte.py`. If it is missing, the scripts stop and say that step 3 has to run first.
