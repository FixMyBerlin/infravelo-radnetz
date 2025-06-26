# Processing Script

**`main.py`** is the start of the processing script. It selects all OSM ways, which are in `BUFFER_METERS` distance to the Radvorrangsnetz.

The `orthogonal_filter.py` is an optional processing step, which additionally:
* Selects short OSM Ways which are less length than `short_way_threshold`.
* Calculates a vector of the Radvorrangsnetz edges in `buffer_meters` distance.
* Throws out segments which are in greater difference than `angle_diff_threshold`.

These ways are usually crossings, which are not parallel to the whished Radvorrangsnetz.

The script creates intermediate geodata versions. This enables to speed up the scripts speed when rerunning. But this can also relate to **caching issues**. So be aware, and be free to delete the `output` folder when having issues.

*Tested with Python 3.13.3.*