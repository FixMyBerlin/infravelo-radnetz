import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'

type Props = {
  sourceLayer: string
}

export const RoadLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      {/* Main style layer */}
      <Layer
        id="roads-line"
        type="line"
        source="roads"
        paint={{
          'line-color': 'pink',
          'line-opacity': 0.8,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      {/* Arrow layer */}
      <Layer
        id="roads-arrow"
        type="symbol"
        source="roads"
        layout={{
          'symbol-placement': 'line',
          'icon-image': 'arrow-image',
          'icon-size': 0.25,
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'icon-rotation-alignment': 'map',
        }}
        paint={{
          'icon-color': 'pink',
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
