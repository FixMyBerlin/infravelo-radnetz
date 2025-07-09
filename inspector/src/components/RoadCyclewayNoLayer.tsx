import { Fragment } from 'react'
import { Layer } from 'react-map-gl/maplibre'
import { MISSING_COLOR, PRESENT_COLOR, UNDEFINED_COLOR } from './shared/cyclewayNoStyle'

type Props = {
  sourceLayer: string
}

export const RoadCyclewayNoLayer = ({ sourceLayer }: Props) => {
  return (
    <Fragment>
      <Layer
        id="roads-cycleway-no-line"
        type="line"
        source="roads"
        paint={{
          'line-color': [
            'case',
            [
              'any',
              ['!', ['has', 'bikelane_left']],
              ['!', ['has', 'bikelane_right']],
              ['!', ['has', 'bikelane_self']],
            ],
            UNDEFINED_COLOR,
            [
              'any',
              ['==', ['get', 'bikelane_left'], 'missing'],
              ['==', ['get', 'bikelane_right'], 'missing'],
              ['==', ['get', 'bikelane_self'], 'missing'],
            ],
            MISSING_COLOR,
            PRESENT_COLOR,
          ],
          'line-opacity': 0.8,
          'line-width': 3,
        }}
        source-layer={sourceLayer}
      />
    </Fragment>
  )
}
