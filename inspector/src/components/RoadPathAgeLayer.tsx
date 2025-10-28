import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathAgeLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('roadsPathAge')

  return (
    <Layer
      id="roadsPath-age-line"
      type="line"
      source="roadsPathClasses"
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
