import { Layer } from 'react-map-gl/maplibre'

type Props = {
  sourceLayer: string
}

export const BikeLaneLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="bikelanes-line"
      type="line"
      source="bikelanes"
      paint={{
        'line-color': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          'black',
          ['boolean', ['feature-state', 'selected'], false],
          'pink',
          'pink',
        ],
        'line-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 1, 0.8],
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
