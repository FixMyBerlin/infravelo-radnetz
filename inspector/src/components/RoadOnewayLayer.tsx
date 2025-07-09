import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getOnewayOpacity, getRoadOnewayColor } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-oneway-line"
        type="line"
        source="roads"
        paint={{
          'line-color': getRoadOnewayColor,
          'line-opacity': getOnewayOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      <Layer
        id="roads-oneway-arrow"
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
          'icon-color': getRoadOnewayColor,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
