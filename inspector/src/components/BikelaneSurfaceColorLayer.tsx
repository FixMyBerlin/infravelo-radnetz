import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getSurfaceColorOpacity, getSurfaceColorStyle } from './shared/surfaceColorStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneSurfaceColorLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-surface-color-line"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getSurfaceColorStyle,
          'line-opacity': getSurfaceColorOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
