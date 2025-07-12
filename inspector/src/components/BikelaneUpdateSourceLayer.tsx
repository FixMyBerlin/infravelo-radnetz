import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { getUpdateSourceOpacity, getUpdateSourceStyle } from './shared/updateSourceStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneUpdateSourceLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="bikelanes-update-source"
        type="line"
        source="bikelanes"
        paint={{
          'line-color': getUpdateSourceStyle,
          'line-opacity': getUpdateSourceOpacity,
          'line-width': 4,
        }}
        filter={['has', 'updated_by']}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
