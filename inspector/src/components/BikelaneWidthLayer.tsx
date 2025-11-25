import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getWidthOpacity, getWidthStyle } from './shared/widthStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneWidthLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('bikelanesWidth')

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
      {...(filter && { filter })}
      beforeId="static-layers-start"
    />
  )
}
