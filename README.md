# infraVelo Radnetz

This project aims to convert already processed [TILDA](https://tilda-geo.de/) OpenStreetMap bicycle geodata to the [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) of Berlin.

## QA
The inspector is useful for QA purposes.

Start by running:
```sh
cd inspector && npm run dev
```

## Processing

*Uses Python and libraries for processing.*

Consider creating a `venv` environment for the script and then install the the dependencies via `requirements.txt`

After creating the environment, run:
```sh
# orthogonalfilter is optional
./.venv/bin/python processing/main.py --orthogonalfilter
```

The output is saved under `output/`.

The processing uses two data sources as inputs: [Radvorrangsnetz](https://tilda-geo.de/regionen/berlin?map=9.9/52.518/13.372&config=1swjsz2.5ount0.4qfsxw.2t61&data=radverkehrsnetz--v&v=2), TILDA data and Detailnetz  is working in two steps:

1. Use the Radvorrangnetz and OpenStreetMap data to assign the Detailnetz Edge ID to the OSM Ways and the OSM Way IDs to the Detailnetz Edges.
2. Glue the OSM data to the Detailnetz, creating bicycle edges in Detailnetz.
