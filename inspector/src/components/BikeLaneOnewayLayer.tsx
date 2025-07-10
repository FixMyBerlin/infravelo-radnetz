import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getBikeLaneOnewayColor, getOnewayOpacity } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-oneway-line"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getBikeLaneOnewayColor,
          'line-opacity': getOnewayOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      <Layer
        id="bikelanes-oneway-arrow"
        type="symbol"
        source="bikelanes"
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
