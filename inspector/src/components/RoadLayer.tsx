import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'

type Props = {
  sourceLayer: string
}

export const RoadLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-line"
        type="line"
        source="roads"
        paint={{
          'line-color': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            'black',
            ['boolean', ['feature-state', 'selected'], false],
            'red',
            'pink',
          ],
          'line-opacity': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            1,
            0.8,
          ],
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />

      <Layer
        id="roads-arrow"
        type="symbol"
        source="roads"
        layout={{
          'symbol-placement': 'line',
          'icon-image': 'arrow-image',
          'icon-size': 0.25,
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'icon-rotation-alignment': 'map',
        }}
        paint={{
          'icon-color': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            'black',
            ['boolean', ['feature-state', 'selected'], false],
            'red',
            'pink',
          ],
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
