import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getSurfaceSettColor, getSurfaceSettOpacity } from './shared/surfaceSettStyle'

type Props = {
  sourceLayer: string
}

export const RoadSurfaceSettLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('roadsSurface')

  return (
    <Fragment>
      <Layer
        id="roads-surface-sett-line"
        type="line"
        source="roads"
        paint={{
          'line-color': getSurfaceSettColor,
          'line-opacity': getSurfaceSettOpacity,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
        {...(filter && { filter })}
        beforeId="static-layers-start"
      />
    </Fragment>
  )
}
