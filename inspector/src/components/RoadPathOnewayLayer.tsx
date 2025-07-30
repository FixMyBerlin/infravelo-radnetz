import { Layer } from 'react-map-gl/maplibre'
import { getBikeLaneOnewayColor, getOnewayOpacity } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="roadsPath-oneway-line"
      type="line"
      source="roadsPathClasses"
      paint={{
        'line-color': getBikeLaneOnewayColor,
        'line-opacity': getOnewayOpacity,
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
