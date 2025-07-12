import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getUpdateSourceOpacity, getUpdateSourceStyle } from './shared/updateSourceStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathUpdateSourceLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="paths-update-source"
        type="line"
        source="roadsPathClasses"
        paint={{
          'line-color': getUpdateSourceStyle,
          'line-opacity': getUpdateSourceOpacity,
          'line-width': 4,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
