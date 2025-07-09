import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getSurfaceSettColor, getSurfaceSettOpacity } from './shared/surfaceSettStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneSurfaceSettLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-surface-sett-line"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getSurfaceSettColor,
          'line-opacity': getSurfaceSettOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
