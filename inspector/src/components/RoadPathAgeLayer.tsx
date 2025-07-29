import { Layer } from 'react-map-gl/maplibre'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathAgeLayer = ({ sourceLayer }: Props) => {
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
    />
  )
}
