import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadAgeLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('roadsAge')

  return (
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
      {...(filter && { filter })}
      beforeId="static-layers-start"
    />
  )
}
