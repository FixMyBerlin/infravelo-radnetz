import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getTrafficSignOpacity, getTrafficSignStyle } from './shared/trafficSignStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneTrafficSignLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-traffic-sign-line"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getTrafficSignStyle,
          'line-opacity': getTrafficSignOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
