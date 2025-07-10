import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getMapillaryOpacity, getMapillaryStyle } from './shared/mapillaryStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneMapillaryLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-mapillary-line"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getMapillaryStyle,
          'line-opacity': getMapillaryOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
