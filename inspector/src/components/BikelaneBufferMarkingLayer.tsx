import { Layer } from 'react-map-gl/maplibre'
import { getBufferMarkingOpacity, getBufferMarkingStyle } from './shared/bufferMarkingStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneBufferMarkingLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-buffer-marking"
      type="line"
      source="bikelanes"
      source-layer={sourceLayer}
      paint={{
        'line-color': getBufferMarkingStyle,
        'line-opacity': getBufferMarkingOpacity,
        'line-width': 4,
      }}
    />
  )
}
