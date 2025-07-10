import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadAgeLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-age-line"
        type="line"
        source="roads"
        paint={{
          'line-color': getAgeColor,
          'line-opacity': getAgeOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      <Layer
        id="roads-age-arrow"
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
          'icon-color': getAgeColor,
          'icon-opacity': getAgeOpacity,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
