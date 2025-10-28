import { Layer } from 'react-map-gl/maplibre'
import { useLayerFilter } from '../hooks/useLayerFilter'
import { getBikeLaneOnewayColor, getOnewayOpacity } from './shared/onewayBasedStyle'

type Props = {
  sourceLayer: string
}

export const RoadPathOnewayLayer = ({ sourceLayer }: Props) => {
  const filter = useLayerFilter('roadsPathOneway')

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
      {...(filter && { filter })}
      beforeId="static-layers-start"
    />
  )
}
