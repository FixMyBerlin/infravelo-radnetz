import { Fragment } from 'react'
import type { ExpressionSpecification } from 'maplibre-gl'
import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getUpdateSourceOpacity, getUpdateSourceStyle } from './shared/updateSourceStyle'

type Props = {
  sourceLayer: string
}

export const RoadUpdateSourceLayer = ({ sourceLayer }: Props) => {
  const colorFilter = useLayerFilter('roadsUpdateSource')

  // Combine the base filter (has updated_by) with color filter
  const combinedFilter: ExpressionSpecification = colorFilter
    ? (['all', ['has', 'updated_by'], colorFilter] as ExpressionSpecification)
    : (['has', 'updated_by'] as ExpressionSpecification)

  return (
    <Fragment>
      <Layer
        id="roads-update-source"
        type="line"
        source="roads"
        paint={{
          'line-color': getUpdateSourceStyle,
          'line-opacity': getUpdateSourceOpacity,
          'line-width': 4,
        }}
        filter={combinedFilter}
        source-layer={sourceLayer}
        beforeId="static-layers-start"
      />
    </Fragment>
  )
}
