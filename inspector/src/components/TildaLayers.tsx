import { Fragment } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import { getTilesUrl, type ENV } from './utils/getTilesUrl'

// Use this type utility to get a union of string literals from a readonly array
// Example: type Source = ArrayElement<typeof sources>
// type ArrayElement<T extends readonly unknown[]> = T[number]

// type Source = ArrayElement<typeof sources>

export const TildaLayers = ({ source }: { source: string }) => {
  const envKey = source.toLocaleLowerCase() as ENV
  return (
    <Fragment>
      <Source
        id="bikeinfra"
        type="vector"
        tiles={[getTilesUrl('/atlas_generalized_bikelanes/{z}/{x}/{y}', envKey)]}
      />
      <Layer
        id="bikeinfra"
        type="line"
        source="bikeinfra"
        source-layer="default"
        paint={{
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, 1],
          'line-color': '#27272a',
          'line-opacity': 0.7,
          'line-offset': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, -0.5],
        }}
      />
      <Source
        id="roads"
        type="vector"
        tiles={[getTilesUrl('/atlas_generalized_roads/{z}/{x}/{y}', envKey)]}
      />
      <Layer
        id="roads"
        type="line"
        source="roads"
        source-layer="default"
        paint={{
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, 1],
          'line-color': '#27272a',
          'line-opacity': 0.7,
          'line-offset': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, -0.5],
        }}
      />
      <Source
        id="path"
        type="vector"
        tiles={[getTilesUrl('/atlas_generalized_roadspathclasses/{z}/{x}/{y}', envKey)]}
      />
      <Layer
        id="path"
        type="line"
        source="path"
        source-layer="default"
        paint={{
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, 1],
          'line-color': '#27272a',
          'line-opacity': 0.7,
          'line-offset': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, -0.5],
        }}
      />
    </Fragment>
  )
}
