import { Layer } from 'react-map-gl/maplibre'
import { getBikeLaneOnewayColor, getOnewayOpacity } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const BikeLaneOnewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-oneway-line"
      type="line"
      source="bikelanes"
      paint={{
        'line-color': getBikeLaneOnewayColor,
        'line-opacity': getOnewayOpacity,
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
