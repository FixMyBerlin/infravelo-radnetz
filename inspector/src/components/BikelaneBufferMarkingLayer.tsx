import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getBufferMarkingOpacity, getBufferMarkingStyle } from './shared/bufferMarkingStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneBufferMarkingLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('bikelanesBufferMarking')

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
      {...(filter && { filter })}
      beforeId="static-layers-start"
    />
  )
}
