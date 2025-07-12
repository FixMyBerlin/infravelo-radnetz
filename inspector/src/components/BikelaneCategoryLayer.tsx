import { Layer } from 'react-map-gl/maplibre'
import { getCategoryOpacity, getCategoryStyle } from './shared/categoryStyle'

type Props = {
  sourceLayer: string
}

export const BikelaneCategoryLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-category"
      type="line"
      source="bikelanes"
      source-layer={sourceLayer}
      paint={{
        'line-color': getCategoryStyle,
        'line-opacity': getCategoryOpacity,
        'line-width': 4,
      }}
    />
  )
}
