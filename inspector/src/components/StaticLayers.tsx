import { Fragment } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'

export const StaticLayers = () => {
  return (
    <Fragment>
      {/* Marker layer to ensure static layers are on top */}
      <Layer id="static-layers-start" type="background" paint={{ 'background-opacity': 0 }} />

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
          'line-opacity': 0.8,
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
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 0, 0.99, 13.5, 0.95, 14, 0.7],
        }}
      />

      <Source
        id="gebiete-mapper"
        type="vector"
        url="pmtiles://https://tilda-geo.de/api/uploads/infravelo-mapping-aufteilung"
      />
      <Layer
        id="gebiete-mapper-border"
        type="line"
        source="gebiete-mapper"
        source-layer="default"
        filter={['==', '$type', 'Polygon']}
        paint={{
          'line-width': 2,
          'line-color': 'white',
          'line-dasharray': [1, 5],
          'line-opacity': 1,
          'line-offset': 0,
        }}
      />
    </Fragment>
  )
}
