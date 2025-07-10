import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getSurfaceSettColor, getSurfaceSettOpacity } from './shared/surfaceSettStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathSurfaceSettLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-path-surface-sett-line"
        type="line"
        source="roadsPathClasses"
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
