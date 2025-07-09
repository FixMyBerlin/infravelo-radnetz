import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getBikeLaneOnewayColor, getOnewayOpacity } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roadsPath-oneway-line"
        type="line"
        source="roadsPathClasses"
        paint={{
          'line-color': getBikeLaneOnewayColor,
          'line-opacity': getOnewayOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      <Layer
        id="roadsPath-oneway-arrow"
        type="symbol"
        source="roadsPathClasses"
        layout={{
          'symbol-placement': 'line',
          'icon-image': 'arrow-image',
          'icon-size': 0.25,
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'icon-rotation-alignment': 'map',
        }}
        paint={{
          'icon-color': getBikeLaneOnewayColor,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
