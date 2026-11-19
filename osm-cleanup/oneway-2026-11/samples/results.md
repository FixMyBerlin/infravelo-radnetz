# Sample: OSM history of 66 safe matches (2026-11-17)

Three Haiku agents, only GET requests to api.openstreetmap.org (way history, changeset tags). Per way: the version that set the tag, the account, the changeset comment, warning signs.

| Group | checked | tag set by FMC |
| --- | ---: | ---: |
| b (last edit by FMC) | 29 | 28 |
| c (not FMC, within the period) | 18 | 3 |
| rest | 19 | 12 |

No hits for: `oneway=yes|-1`/roundabout at the time of tagging with later removal (except Perleberger Straße), direction words in the changeset comment (links, Gegenrichtung, contraflow), today's `oneway` other than `no`, `oneway:bicycle`.

Notable (deleting is still right):

| Way | Rule | Finding |
| --- | --- | --- |
| [375958863](https://www.openstreetmap.org/way/375958863), [376545734](https://www.openstreetmap.org/way/376545734) | R3 | Perleberger Straße, bus lane on the left. fmc_6 set the tag when the street was `oneway=yes` (cs 174091895), mardiz removed `oneway` later (cs 176142350, 185541105). Tag outdated today; confirm the bus lane on site. |
| [1044393274](https://www.openstreetmap.org/way/1044393274) | R3 | In the same edit left lane → crossing; no lane on the left any more. The lane may have been lost. |
| [8149664](https://www.openstreetmap.org/way/8149664) | R1 | `cycleway:both=crossing` since fmc_10 (cs 174881457), lane before (fmc_6). Disputed. |
| [1428277347](https://www.openstreetmap.org/way/1428277347) | R1 | Left lane ↔ crossing back and forth between fmc_6 and Traffikant; construction cycleway on the right. |

Already cleaned up since the extract (fmc_6, cs 191910176 "RVA Radnetz …" and 191737591): 240451922, 1089751336, 1089751368, 844026237, 1494449306, 1494449307, 1429738191. Touched since the extract, tag still there: 152264795, 1001886268 (fmc_7, 11.11.).

Not set by FMC: 23 of the 66. Of these Traffikant 18 (comments like "specify cycleway (traffic_sign oneway segregated, width)", Oct./Nov. 2025), Supaplex030 2 (Heinrich-Heine-Straße, Dec. 2025), klnkengi 2 ("Radroute Industriekultur Berlin 1", `source=survey`, both already cleaned up), kartograph 1.

Raw history data: scratchpad of the session (`hist/`, `cs/`), not kept.
