# Processing Script

**`main.py`** is the start of the processing script. It selects all OSM ways, which are in `BUFFER_METERS` distance to the Radvorrangsnetz.

The script creates intermediate geodata versions. This enables to speed up the scripts speed when rerunning. But this can also relate to **caching issues**. So be aware, and be free to delete the `output` folder when having issues.

*Tested with Python 3.13.3.*

## Filters

Every filter has it's own Python module and flag.

See also: `./.venv/bin/python processing/main.py -h`.

### Orthogonal Filter

**`--orthogonalfilter-bikelanes`** for bikelanes dataset.<br/>
**`--orthogonalfilter-streets`** for streets dataset.

The `orthogonal_filter.py` is an optional processing step, which additionally:
* Selects short OSM Ways which are less length than `short_way_threshold`.
* Calculates a vector of the Radvorrangsnetz edges in `buffer_meters` distance.
* Throws out segments which are in greater difference than `angle_diff_threshold`.

These ways are usually crossings, which are not parallel to the whished Radvorrangsnetz.

### Manual OSM Inclusion & Exclusions

**`--manual-interventions`**

Uses the files `data/exclude_ways.txt` and `data/include_way.txt` one OSM way id per line and excludes or includes the OSM way into the dataset.

### Difference

**`--difference-streets-bikelanes`**

Calculate difference between two datasets. Usually used for determinating all streets, where no bikelanes has been detected in OSM.

### Process Steps

Useful, when developing on another processing step.

**`--skip-bikelanes`** skips the processing of bikelanes dataset completely.
**`--skip-streets`** skips the processing of streets dataset completely. 