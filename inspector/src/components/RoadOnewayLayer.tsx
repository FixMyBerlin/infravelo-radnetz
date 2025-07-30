import { Layer } from 'react-map-gl/maplibre'
import { getOnewayOpacity, getRoadOnewayColor } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="roads-oneway-line"
      type="line"
      source="roads"
      paint={{
        'line-color': getRoadOnewayColor,
        'line-opacity': getOnewayOpacity,
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
