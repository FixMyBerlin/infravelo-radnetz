import { Layer } from 'react-map-gl/maplibre'

type Props = {
  sourceLayer: string
}

export const RoadPathLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="roadsPathClasses-line"
      type="line"
      source="roadsPathClasses"
      paint={{
        'line-color': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          'black',
          ['boolean', ['feature-state', 'selected'], false],
          'pink',
          'purple',
        ],
        'line-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 1, 0.8],
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
