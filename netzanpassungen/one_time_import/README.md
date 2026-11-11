# One-time import into the Netzanpassungen app

This folder holds a file that is uploaded **once** into the Netzanpassungen app (KV database) and is an archive afterwards. The pipeline never reads this folder. Manual work lives in the app; `apply_app_result.py` writes everything the pipeline needs from it to `netzanpassungen/output/`.

Converted on 2026-11-11 from the old override lists. It is uploaded in the "Gebiet" step of the app with "Einträge einspielen" (area Berlin). Nothing changes here afterwards; whoever needs a correction makes it in the app.

| File | Content | Origin |
|---|---|---|
| `altlisten_korrekturen.json` | 38 `edge_correction` entries (`von_nutzer: "Altliste"`): `verkehrsrichtung` from `rvn_korrekturen.csv` (18) and `opposite_edge_overwrite_element_nr.txt` (1, mode `remove`, only Detailnetz B to R), plus 19 exclusions from `ausschluss_element_nr.csv` (Tunnel Tiergarten, motorway feeders). `kommentar` is the reason given in the list | The three lists were converted with a one-time script (not in the repo) and deleted |

## The 53 virtual nodes of 2025 are not in this folder

They were delivered with fixed names, so they are **not** imported into the app. They are a fixed, read-only input of step 1 (like the Detailnetz nodes): [`data/virtuelle_knoten_2025.gpkg`](../../data/virtuelle_knoten_2025.gpkg) (layer `Virtuelle-Knotenpunkte`, column `Knotenpunkt-ID`, EPSG:25833). `ren-network/merge_networks.py` splits the REN+ edges at them and numbers the edges from them; they reach the app as `knoten` with `ist_virtuell = 1` in the app input.

Where all virtual nodes end up: `apply_app_result.py` writes the 2025 nodes, the automatic nodes of step 1 and the nodes drawn in the app to `netzanpassungen/output/virtuelle_knoten.gpkg`. `processing/` and `knotenpunkte/` read that file through `processing/helpers/virtuelle_knoten.py`. If it is missing, the scripts stop and say that step 3 has to run first.
