import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { CANDIDATE_COLOR, PRESENT_COLOR } from './shared/dualCarrigewayStyle'

type Props = {
  sourceLayer: string
}

export const RoadDualCarriagewayLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-dual-carriageway-line"
        type="line"
        source="roads"
        paint={{
          'line-color': [
            'case',
            ['==', ['get', 'oneway'], 'yes_dual_carriageway'],
            PRESENT_COLOR,
            [
              'all',
              ['has', 'oneway'],
              ['==', ['get', 'oneway'], 'yes'],
              [
                '!',
                [
                  'any',
                  ['==', ['get', 'road'], 'residential'],
                  ['==', ['get', 'road'], 'service_road'],
                  ['==', ['get', 'road'], 'living_street'],
                  ['==', ['get', 'road'], 'bicycle_road'],
                  ['==', ['get', 'road'], 'motorway'],
                  ['==', ['get', 'road'], 'motorway_link'],
                ],
              ],
            ],
            CANDIDATE_COLOR,
            'transparent',
          ],
          'line-opacity': 0.8,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
