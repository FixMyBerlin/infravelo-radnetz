import { Fragment } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'

export const StaticLayers = () => {
  return (
    <Fragment>
      <Source
        id="vorrangnetz-mask"
        type="vector"
        url="pmtiles://https://tilda-geo.de/api/uploads/radverkehrsnetz-vorrangnetz-mask"
      />
      <Layer
        id="vorrangnetz-mask-border"
        type="line"
        source="vorrangnetz-mask"
        source-layer="default"
        filter={['==', '$type', 'Polygon']}
        paint={{
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, 1],
          'line-color': '#27272a',
          'line-opacity': 0.7,
          'line-offset': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, -0.5],
        }}
      />
      <Layer
        id="vorrangnetz-mask-fill"
        type="fill"
        source="vorrangnetz-mask"
        source-layer="default"
        filter={['==', '$type', 'Polygon']}
        paint={{
          'fill-color': '#27272a',
          'fill-opacity': 0.3,
        }}
      />
    </Fragment>
  )
}
