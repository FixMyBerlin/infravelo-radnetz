# Network pipeline: from the raw network to the customer network and the working network

As of 2026-11-18. Two repos take part: this repo `infravelo-radnetz` (Python, all network files) and [`radnetz-apps`](https://github.com/FixMyBerlin/radnetz-apps) with the **Netzanpassungen app** (`netzanpassungen/` there, handwork in the KV database). The app itself is described in its [README](https://github.com/FixMyBerlin/radnetz-apps/blob/main/netzanpassungen/README.md).

> **Status:** the parts on virtual nodes describe the agreed target after merging the registry of virtual nodes from `main` (`data/VIRTUELLE-KNOTENPUNKTE.md`). They are being built on branch `claude/netzkorrektur`; until then the code still follows the older text in the git history of this file.

**Language rule for both repos:** code, comments, file names, commit messages and our documents are in English. The app UI and the customer's data fields (`element_nr`, `verkehrsrichtung`, `routen_fernradweg`, `fahrbahn_typ`, …) stay German.

## Principle

**The Netzanpassungen app sits in the middle of the pipeline and never receives anything from the end of it.** Its input holds only raw data, what is computed automatically, and the registry of virtual nodes. All other handwork (new edges, assignments, corrections) lives only in the KV database and is laid onto this input at every load. That is why the input file can be regenerated and uploaded at any time: nothing is duplicated, and nothing has to be recognised as "already taken over".

**One exception: virtual nodes.** Their numbers are given in one place only, the registry `data/Virtuelle-Knotenpunkte.gpkg`, and only by `data/virtuelle_knotenpunkte.py` (rules: [`data/VIRTUELLE-KNOTENPUNKTE.md`](../data/VIRTUELLE-KNOTENPUNKTE.md)). A node drawn in the app has a provisional name (`neu-<n>`) until step 3 takes it into the registry. The registry recognises nodes it already has by `app_eintrag`, so the round trip creates no duplicates.

For Python this means: the result of the app is written only to `output/`, never to `data/`, except new virtual nodes into the registry.

## Result

| File                       | Content                                                                                                                                                                                                                                                                                                                          | For                                                      |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `ren_netz.gpkg`            | Raw network split at all active virtual nodes + Radfernwege (assigned automatically and by hand) + newly drawn edges + direction, carriageway and excluded edges. Everything that comes from the Netzanpassungen app is marked in its own columns (e.g. `quelle_eintrag`, `verkehrsrichtung_korrigiert`, `ausgeschlossen`, `grund`). **No** position corrections. | customer                                                 |
| `ren_netz_korrigiert.gpkg` | like `ren_netz.gpkg`, plus the position corrections (geometry)                                                                                                                                                                                                                                                                   | matching (`processing/map-matching`) and mapping (TILDA) |
| `data/Virtuelle-Knotenpunkte.gpkg` | the registry: every virtual node with its four-digit number, active or deleted                                                                                                                                                                                                                                          | every script and app that needs node ids                 |

Both networks also come as the filtered mapping version (`…_kartierung…`). The only difference between the two networks is position: without the columns on the overrides the customer would not understand what we did, which is why they are in the customer version too.

## Diagram

```mermaid
flowchart TD
  subgraph IN["Input data: infravelo-radnetz/data"]
    DN["Berlin Straßenabschnitte Detailnetz &lt;date&gt;.fgb<br/><i>all streets, element_nr, official node ids (8 digits)</i>"]
    RQ["netzquellen/radverkehrsnetz.gpkg<br/>netzquellen/radschnellverbindungen.gpkg<br/>netzquellen/hauptstrassennetz.gpkg<br/><i>cycle network sources</i>"]
    RF["netzquellen/touristisches_radnetz.gpkg<br/><i>long-distance cycle routes, GPS lines</i>"]
    VK["<b>Virtuelle-Knotenpunkte.gpkg</b><br/><i>registry of virtual nodes: four-digit number,<br/>active or deleted, the 53 of 2025 are 0001–0053</i>"]
  end

  VT["data/virtuelle_knotenpunkte.py<br/><i>the only place that gives numbers:<br/>number new points, take over, delete</i>"]
  QG["QGIS<br/><i>set or move a point by hand</i>"]
  EU["netzanpassungen/one_time_import/<br/>altlisten_korrekturen.json<br/><i>corrections from the old override lists,<br/>loaded once into the app</i>"]

  S1["<b>Step 1: merge the network</b><br/>ren-network/merge_networks.py<br/><i>splits edges at the active virtual nodes,<br/>unique element_nr per edge</i>"]
  R1["output: ren_netz_roh.gpkg"]
  P1["output: virtuelle_knoten_vorschlaege.gpkg<br/><i>where edges meet without a node:<br/>proposals, no numbers</i>"]

  S2["<b>Step 2: assign Radfernwege automatically</b><br/>netzanpassungen/match_cycle_routes.py"]
  R2["output: ren_netz_auto.gpkg<br/><i>+ routen_fernradweg, taken-in Detailnetz edges</i>"]
  L2["output: radfernweg_abschnitte.gpkg<br/><i>every Radfernweg in sections, fixed id</i>"]

  AE["<b>Write the app input</b><br/>netzanpassungen/write_app_input.py"]
  AI["output: netzanpassungen_&lt;gebiet&gt;.json<br/><i>Detailnetz, REN+, Radfernwege, sections,<br/>nodes with their numbers and app_eintrag</i>"]

  APP["<b>Netzanpassungen app</b><br/>resolve gaps, position corrections, direction,<br/>carriageway, exclusion, new edges,<br/>new virtual nodes (provisional name neu-&lt;n&gt;)<br/><i>all in the KV database</i>"]
  EX["netzanpassungen-eintraege-&lt;gebiet&gt;-&lt;date&gt;.json<br/><i>export „Alle Einträge“</i>"]

  S3["<b>Step 3: apply the app result</b><br/>netzanpassungen/apply_app_result.py<br/><i>takes new app nodes into the registry first</i>"]
  R3K["output: ren_netz.gpkg<br/><i>customer version, everything marked,<br/>no position corrections</i>"]
  R3W["output: ren_netz_korrigiert.gpkg<br/><i>working version: + position corrections</i>"]

  PR["processing/<br/><i>RVN and Detailnetz split at the registry nodes</i>"]
  MM["processing/map-matching"]
  TI["TILDA, Mapper"]
  KP["knotenpunkte/build_knotenpunkte.py<br/><i>every node of REN+ not rated in 2025<br/>goes to the Knotenpunkte app</i>"]
  RW["ren-network/map_back_to_original.py<br/><i>matching result by element_nr onto ren_netz.gpkg</i>"]
  KU["Customer"]

  QG --> VT
  P1 -. "checked, then numbered" .-> VT
  VT --> VK
  RQ --> S1
  DN --> S1
  VK --> S1
  S1 --> R1
  S1 --> P1
  R1 --> S2
  DN --> S2
  RF --> S2
  S2 --> R2
  S2 --> L2
  R2 --> AE
  VK --> AE
  DN --> AE
  RF --> AE
  L2 --> AE
  AE --> AI
  AI --> APP
  EU -. "once: Einträge einspielen" .-> APP
  APP --> EX
  R2 --> S3
  EX --> S3
  S3 -- "new app nodes get their number" --> VT
  S3 --> R3K
  S3 --> R3W
  VK --> PR
  VK --> KP
  R3K --> KP
  R3W --> MM
  R3W --> TI
  MM --> RW
  R3K --> RW
  RW --> KU
  R3K --> KU
```

**The round trip of a new virtual node:** drawn in the app as `neu-3` → exported with „Alle Einträge“ → step 3 takes it into the registry as `0054` (with `app_eintrag`) and splits its edge in `ren_netz.gpkg` → the next app input carries `0054`; the app hides its own entry and shows the node with its number. Until the next run of steps 1 and 2 the edge is split only in the result of step 3, not yet in the app input.

## The steps

Script and file names (renamed with this rebuild):

| before                                                             | now                                     |
| ------------------------------------------------------------------ | --------------------------------------- |
| `ren-network/unify_networks.py`, `netz_zusammenfuehren.py`         | `ren-network/merge_networks.py`         |
| `ren-network/output/ren_netz_gesamt.gpkg`                          | `ren-network/output/ren_netz_roh.gpkg`  |
| `netzanpassungen/radfernwege_zuordnen.py`                          | `netzanpassungen/match_cycle_routes.py` |
| `netzanpassungen/export_app_daten.py`, `app_eingabe_schreiben.py`  | `netzanpassungen/write_app_input.py`    |
| `netzanpassungen/import_app_export.py`, `app_ergebnis_anwenden.py` | `netzanpassungen/apply_app_result.py`   |
| `ren-network/zurueck_aufs_original.py`                             | `ren-network/map_back_to_original.py`   |
| `netzanpassungen/einmalige_uebernahme/`                            | `netzanpassungen/one_time_import/`      |

**Virtual nodes.** A virtual node is a node the Detailnetz does not have. Every one of them is in the registry `data/Virtuelle-Knotenpunkte.gpkg` with a four-digit number that never changes. It gets there in three ways, and every way ends in `data/virtuelle_knotenpunkte.py`:

- **QGIS:** set the point by hand, then `virtuelle_knotenpunkte.py nummerieren`.
- **App:** draw it in the Netzanpassungen app; step 3 takes it over (the same rule as `virtuelle_knotenpunkte.py uebernehmen`, which also works on its own with the app export „Virtuelle Knoten“).
- **Proposals of step 1:** where REN+ edges meet without any node, step 1 writes a proposal. Proposals have no number and change nothing until someone checks them and takes them into the registry. On all of Berlin there are 340 such places (141 on the interior of another edge, 187 where edge ends meet, 12 open ends).

Every virtual node that is an end of a REN+ edge becomes a Knotenpunkt and is rated like any other node that was not rated in 2025 (`knotenpunkte/README.md`). New nodes therefore go into a new dataset for the Knotenpunkte app.

**Step 1: merge the network** (`ren-network/merge_networks.py`). Raw data merge: Radverkehrsnetz, Radschnellverbindungen, Hauptstraßennetz; `element_nr` through the node pairs of the Detailnetz. Then the REN+ edges are split at the active nodes of the registry, and every edge gets a unique `element_nr` from its end nodes (`<von>_<bis>.<nn>`; split pieces keep the old number in `ursprung_element_nr`). Reason for the unique number: 234 REN+ rows had no `element_nr` and 17 numbers occurred twice. Result `ren_netz_roh.gpkg` and the proposals `virtuelle_knoten_vorschlaege.gpkg`. No link to Radfernwege or to the app.

**Step 2: assign Radfernwege automatically** (`netzanpassungen/match_cycle_routes.py`). Every Radfernweg is laid onto REN+ and the Detailnetz (rule below). Clearly matching REN+ edges get `routen_fernradweg`. Clearly matching Detailnetz edges that are not in REN+ yet (Markgrafenstraße) are taken in, with `grund_aufnahme = radfernweg`. What is left becomes a **gap** with a fixed id. No handwork in this step.

**Write the app input** (`netzanpassungen/write_app_input.py`). Writes `netzanpassungen_<gebiet>.json` from `ren_netz_auto.gpkg`, the Detailnetz, the Radfernwege, the Radfernweg sections and the registry. The nodes (`knoten`) are the Detailnetz nodes plus the active virtual nodes with their number, the id they had in 2025 and `app_eintrag`; deleted ones are listed separately. This file is uploaded in the app, also repeatedly.

**One-time import** (`netzanpassungen/one_time_import/`). Only `altlisten_korrekturen.json`: the corrections from the old override lists. It is loaded once into the app („Einträge einspielen“ in the Gebiet view), then it is archive only; the pipeline never reads the folder.

**In the Netzanpassungen app** a gap is resolved like this:

- **draw new** where there is no matching edge
- **assign existing edge(s)**, also REN+ or grey Detailnetz edges further away (rerouting). The deviation between the GPS line and the chosen edges is measured (Hausdorff, area) and highlighted for the talk with the customer.
- **no action needed**

An automatically assigned stretch can be rerouted in the app too. In addition come the position corrections, direction, carriageway and exclusion, and new virtual nodes.

**Step 3: apply the app result** (`netzanpassungen/apply_app_result.py`). Reads `ren_netz_auto.gpkg` and the app export. First it takes the app's new virtual nodes into the registry (they get their numbers; nodes the registry already has are recognised by `app_eintrag`). Then it writes to `output/`:

- `ren_netz.gpkg` (customer): new edges, edges split at the new virtual nodes, gap assignments with their `routen_fernradweg`, direction, carriageway, excluded edges. Every takeover from the app is marked in its own columns, with the id of the KV entry.
- `ren_netz_korrigiert.gpkg` (working): the same plus the position corrections
- `korrekturen_konflikte.csv`

Nothing else from the app goes to `data/`: whatever landed there would come into the app twice through the next app input.

**Old override lists.** The corrections of `data/rvn_korrekturen.csv`, `data/opposite_edge_overwrite_element_nr.txt` and `ren-network/ausschluss_element_nr.csv` are converted into `altlisten_korrekturen.json`. The lists themselves stay until the customer delivery on the Radvorrangnetz (RVN) is done, because that delivery still reads them: `processing/scripts/enrich_rvn_with_detailnetz.py` applies `rvn_korrekturen.csv` to the RVN, and the evaluation of `processing/map-matching` marks the entries of `opposite_edge_overwrite_element_nr.txt` (the matching itself does not use them).

## Assignment rule Radfernweg → edge

Before, there was no assignment, only gaps: everything within 10 m of any REN+ or Detailnetz edge counted as done, the rest from 20 m on was a gap. Places with a Detailnetz edge but no REN+ edge (Markgrafenstraße) fell through. Since the rebuild `netzanpassungen/match_cycle_routes.py` (step 2) does this. The rule is deliberately generous because the GPS lines are less accurate than the network.

**Fixed (as of 2026-11-11, after a run on all of Berlin):**

| Value                        | Start value | **Fixed**                        | Meaning                                                                                                                                    |
| ---------------------------- | ----------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Distance                     | 15 m        | **20 m**                         | A support point of the edge (every 5 m) counts as near when it is at most this far from the route                                          |
| Share                        | 70 %        | **60 %**                         | Share of the edge length that must be near **and** parallel                                                                                |
| Angle                        | 30°         | **45°**                          | Acute angle between edge and route (direction over 8 m each) below which they count as parallel                                            |
| Candidates                   | 40–70 %     | **40–60 %**                      | not taken, but proposed first in the app                                                                                                   |
| Rest without route           | –           | **at most 250 m**                | For long edges even a high share is only taken when no more than 250 m stay without route; otherwise candidate                             |
| Detailnetz edge next to REN+ | –           | **at most 50 % already covered** | A Detailnetz edge that is not in REN+ is only taken in when at most half of its length is carried by assigned REN+ edges of the same route |

**No Hausdorff as a criterion:** it measures the largest distance, so a single GPS jump would reject a matching edge. Hausdorff and the 95th percentile (distance from the section to its edges, one-sided) are on every section as `hausdorff_m` and `p95_m`, so strong deviations can be found in QGIS. Over all assigned sections: median 5.8 m (Hausdorff) and 5.1 m (P95), 90 % below 15 and 14 m, largest Hausdorff 28 m.

**Result on Berlin** (8 routes, 278.8 km, of which 240.2 km in Berlin): 769 sections `auf_ren` (153.9 km), 138 `aufgenommen` (31.1 km, 99 Detailnetz edges, 21.9 km), 121 `luecke` (93.8 km, of which 55.4 km in Berlin). REN+ rows with a Radfernweg: 581 (120.0 km edge length), 195 rows with several routes. For comparison the old gap list: 278 gaps, 102.7 km (64.2 km in Berlin). Of the 55.4 km gap in Berlin, 32.9 km have no edge at all within 20 m (the ways are missing in the Detailnetz and in REN+); for 22.5 km an edge lies nearby but is not parallel, too far away, or already carried by REN+. 25 of the 121 gaps have candidates.

### Evidence from the run

**Distance.** The number of assigned edges grows with the distance until it flattens at about 20 m (REN+ kilometres in Berlin at share 70 %, angle 30°: 10 m 118.0 · 15 m 141.7 · 20 m 151.6 · 30 m 154.5). What matters is what is added when the distance grows:

| Step      | new edges | km   | of which on a stretch that another edge of the route already carried |
| --------- | --------- | ---- | -------------------------------------------------------------------- |
| 10 → 15 m | 119       | 24.7 | 1 edge                                                               |
| 15 → 20 m | 44        | 10.1 | 6 (14 %): e.g. Puschkinallee, Grunerstraße                           |
| 20 → 25 m | 18        | 3.4  | 7 (39 %)                                                             |
| 25 → 30 m | 12        | 1.8  | 9 (75 %)                                                             |

Up to 20 m the new edges almost only fill stretches that were empty before (the GPS line runs 15 to 19 m beside a whole edge, e.g. Heerstraße, Schulzendorfer Straße, Straße des 17. Juni, Lindenstraße). Beyond that they are mostly parallel streets. Hence 20 m.

**Share.** The distribution has two strong peaks (REN+, distance 15 m: 660 of 886 route–edge pairs have 90 to 100 %, in between there are only 14 to 47 per 10 % step), so the threshold decides about few edges only. The touchstone is the connection: if an edge is attached to another, surely assigned edge (same end point within 1 m) it probably belongs to the route; an isolated edge is suspicious.

| Share     | edges | connected at both ends | isolated |
| --------- | ----- | ---------------------- | -------- |
| from 70 % | 767   | 80 %                   | 2 %      |
| 60–70 %   | 18    | 44 %                   | 0 %      |
| 50–60 %   | 13    | 23 %                   | 23 %     |
| 40–50 %   | 11    | 0 %                    | 27 %     |

(Distance 20 m, angle 30°.) Down to 60 % the edge looks like a piece of the route, below that no longer: there the route lies on only a part of the edge and then leaves it. So 60 % for "taken", below that down to 40 % candidate. This takes 18 more REN+ edges than 70 %.

**Angle.** Cross streets: 313 REN+ edges and 493 Detailnetz edges have at least one support point within 20 m of the route but are nowhere parallel below 45°; none of them is taken. What the threshold additionally lets in (distance 20 m, share 60 %):

| Angle    | new edges                  | Finding                                                                                                                       |
| -------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 15 → 20° | 11 (3 isolated)            | curves and GPS spikes                                                                                                         |
| 20 → 30° | 12                         | all connected                                                                                                                 |
| 30 → 45° | 11                         | all connected: roundabouts (Strausberger Platz), square edges                                                                 |
| 45 → 60° | 17, of which 13 Detailnetz | 15 to 19 m long stubs (Angersteinweg, Schloßpark, Nordhafenpark) and ways beside the route (Bulgarische Straße, Betckestraße) |
| 60 → 90° | 55, of which 34 Detailnetz | cross streets, 4 isolated, 10 below 30 m                                                                                      |

Up to 45° only what hangs on the route is added; from 45° the crossing stubs start. Hence 45°.

### Spot checks (all with the fixed values)

The pattern shows the support points of the edge from start to end: `#` near and parallel, `n` near but not parallel, `.` far.

| Case                   | Edge                                                                                        | Share       | Finding                                                                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| just taken             | Alexanderstraße 47550057_47550001.01 (21 m)                                                 | 0.60        | `nn###`: the route turns off at the end; crossing edge of the route, correct                                                                         |
| just taken             | Bahnhofstraße 49630096_49630054.01 (21 m)                                                   | 0.60        | `###nn`: the same                                                                                                                                    |
| just taken             | Strausberger Platz 48540047_48540027.01 (75 m)                                              | 0.60        | roundabout, the GPS line cuts the curve; correct                                                                                                     |
| crossing stub          | Innsbrucker Platz 42500040_42500084.01 (29 m), Puschkinallee 50520043_50520032.01 (27 m)    | 0.67        | short edges at squares, both connected to assigned edges; correct                                                                                    |
| candidate              | An der Wuhlheide 55480001_55480015.01 (191 m, distance 17 m)                                | 0.59        | the first 80 m without route (GPS line jumps); to be decided in the app                                                                              |
| candidate              | Bellevueallee 43540023_43540021.01 (110 m)                                                  | 0.57        | route joins in the middle                                                                                                                            |
| candidate              | Straßentunnel Alexanderplatz 47540406_47550003.01 (693 m)                                   | 0.48        | route runs on the second half only                                                                                                                   |
| candidate (Detailnetz) | Puschkinallee 50510010_50520027.02 (163 m)                                                  | 0.48        | route turns off after 80 m; REN+ already carries the stretch                                                                                         |
| long edge              | Straße zum Müggelhort (Detailnetz, 2452 m)                                                  | 0.60        | 969 m without route: not taken only because of the 250 m limit                                                                                       |
| long edge              | Kladower Damm 31500019_31510004.01 (864 m)                                                  | 0.67        | 285 m without route: candidate as well                                                                                                               |
| GPS distance           | Lindenstraße 68440003_68440016.04 (176 m)                                                   | 1.00        | distance 18.6 m, the whole edge parallel; only taken with 20 m                                                                                       |
| GPS distance           | Großer Stern 42540016_42540018.01 (50 m), Schulzendorfer Straße 58410039_58410025.03 (67 m) | 0.80 / 1.00 | distance 18.4 to 18.5 m; the same                                                                                                                    |
| GPS distance           | Müggelheimer Damm 58460035_59450004.02 (471 m)                                              | 0.76        | `####...............###…`: line 18 m beside it, a jump in the middle; taken                                                                          |
| GPS jump               | Spreeradweg, edge without element_nr (1374 m)                                               | 0.89        | a far piece in the middle (`nnnn###.####…`); taken, exactly what the share should forgive. With Hausdorff as a criterion it would have been rejected |
| GPS jump               | Berlin-Usedom 46580023_46590016.01 (433 m, distance 15.4 m)                                 | 0.64        | the GPS line leaves the edge 150 m before its end; taken                                                                                             |
| parallel street        | Goltzstraße (Detailnetz, three edges, 34 to 109 m)                                          | 1.00        | REN+ already carries the same stretch: not taken in (20 such Detailnetz edges in total)                                                              |
| cross street           | 46550057_47550029.01 (399 m), 47550001_47550003.01 (280 m) and 311 more REN+ edges          | 0           | near, but never parallel below 45°                                                                                                                   |

Small sections: stretches below 25 m of the same state, gaps below 20 m and stretches below 5 m are merged into the neighbouring section. The section id is fixed as long as route, network and these values stay the same; if a value changes, the ids change and old `section_assignment` entries of the app no longer fit (they end up in `korrekturen_konflikte.csv`).

## Decisions

1. **Customer version with overrides** (2026-11-11): direction, carriageway and excluded edges belong in `ren_netz.gpkg` too, clearly marked as our change. Only the position corrections stay out.
2. **Thresholds** of the assignment rule (2026-11-11): set by the implementation after its own check (values above).
3. **Rename** of the scripts and folders together with the rebuild (2026-11-11); English names for code, files, comments, commit messages and documents (language rule above).
4. **Unique `element_nr`** for every REN+ edge, built in step 1 from its end nodes (2026-11-11); the app uses it as the edge ref.
5. **Registry of virtual nodes** (2026-11-18): `data/Virtuelle-Knotenpunkte.gpkg` is the only source of node numbers, `data/virtuelle_knotenpunkte.py` the only place that gives them. Step 1 does not name nodes itself any more; it proposes. Step 3 takes the app's new nodes into the registry.
6. **Virtual nodes are rated** (2026-11-18): a virtual node that is an end of a REN+ edge is a Knotenpunkt and gets rated like the others; new ones go into a new dataset for the Knotenpunkte app.
7. **Old override lists stay until the RVN delivery** (2026-11-18), see above.
