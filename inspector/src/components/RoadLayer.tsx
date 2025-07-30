import { Layer } from 'react-map-gl/maplibre'

type Props = {
  sourceLayer: string
}

export const RoadLayer = ({ sourceLayer }: Props) => {
  return (
    <Layer
      id="roads-line"
      type="line"
      source="roads"
      paint={{
        'line-color': 'pink',
        'line-opacity': 0.8,
        'line-width': 3,
      }}
      source-layer={sourceLayer}
    />
  )
}
