import { Layer } from 'react-map-gl/maplibre'
import { getWidthOpacity, getWidthStyle } from './shared/widthStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneWidthLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-width"
      type="line"
      source="bikelanes"
      source-layer={sourceLayer}
      paint={{
        'line-color': getWidthStyle,
        'line-opacity': getWidthOpacity,
        'line-width': 4,
      }}
    />
  )
}
