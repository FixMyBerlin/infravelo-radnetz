import { Layer } from 'react-map-gl/maplibre'
import { getAgeColor, getAgeOpacity } from './shared/ageBasedStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneAgeLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-age-line"
      type="line"
      source="bikelanes"
      paint={{
        'line-color': getAgeColor,
        'line-opacity': getAgeOpacity,
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
