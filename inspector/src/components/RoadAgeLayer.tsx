import { Layer } from 'react-map-gl/maplibre'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadAgeLayer = ({ sourceLayer }: Props) => {
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
    />
  )
}
