# infraVelo Radnetz

This project aims to convert already processed [TILDA](https://tilda-geo.de/) OpenStreetMap bicycle geodata to the [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) of Berlin.

## QA
The inspector is useful for QA purposes.

Start by running:
```sh
cd inspector && npm run dev
```

Alternatively, you can use the **QGIS** `QGIS QA Processing.qgz` Project, which displays the different output files.

## Processing

*Uses Python and libraries for processing.*

Consider creating a `venv` environment for the script and then install the the dependencies via `requirements.txt`

After creating the environment, run:
```sh
# Assumed, you are in the root repo folder

# Create a venv environment, if not existing:
python3 -m venv .venv

# Activate the venv environment, when opening a new shell:
source .venv/bin/activate

# Install packages in venv environment
pip install -r processing/requirements.txt

# The process needs to be executed in this order
./.venv/bin/python processing/translate_attributes_tilda_to_rvn.py --clip-neukoelln
./.venv/bin/python processing/start_matching.py --clip-neukoelln
./.venv/bin/python processing/start_snapping.py --clip-neukoelln

# To clip new TILDA bikelanes data, execute, then move to data folder
./.venv/bin/python ./scripts/clip_bikelanes.py --input ./bikelanes.fgb --clip-features ./data/"Berlin Bezirke.gpkg" --output "./TILDA Radwege Berlin.fgb"
```

The output is saved in `output/`.

The processing uses two data sources as inputs: [Radvorrangsnetz](https://tilda-geo.de/regionen/berlin?map=9.9/52.518/13.372&config=1swjsz2.5ount0.4qfsxw.2t61&data=radverkehrsnetz--v&v=2), TILDA data and Detailnetz  is working in two steps:

1. Use the Radvorrangnetz and OpenStreetMap data to assign the Detailnetz Edge ID to the OSM Ways and the OSM Way IDs to the Detailnetz Edges.
2. Glue the OSM data to the Detailnetz, creating bicycle edges in Detailnetz.

At the end of the process, the file `matched_osm_ways.fgb` contains all OSM Ways, which are...
* part of the RVN
* are part of the bikelanes, roads or roadsPathClasses TILDA export