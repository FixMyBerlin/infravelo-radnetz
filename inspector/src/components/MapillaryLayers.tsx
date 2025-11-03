import { Fragment } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import { apiKeyMapillary, FMC_CREATOR_IDS, FMC_ORGANIZATION_ID } from '../constants/mapillary'

export const MapillaryAllLayers = () => {
  return (
    <Fragment>
      <Source
        id="mapillary-source"
        type="vector"
        tiles={[
          `https://tiles.mapillary.com/maps/vtp/mly1_public/2/{z}/{x}/{y}?access_token=${apiKeyMapillary}`,
        ]}
        minzoom={0}
        maxzoom={14}
      />
      <Layer
        id="mapillary-point-click-target"
        type="circle"
        source="mapillary-source"
        source-layer="image"
        paint={{
          'circle-radius': 10,
          'circle-color': 'transparent',
        }}
      />
      <Layer
        id="mapillary-point"
        type="circle"
        source="mapillary-source"
        source-layer="image"
        paint={{
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 0.1, 14.5, 3, 15, 3, 17, 5],
          'circle-blur': 0.5,
          'circle-color': [
            'step',
            ['get', 'captured_at'],
            '#F77E5E',
            new Date().setFullYear(new Date().getFullYear() - 4),
            '#FFC01B',
            new Date().setFullYear(new Date().getFullYear() - 2),
            '#05CB63',
          ],
        }}
      />
      <Layer
        id="mapillary-line"
        type="line"
        source="mapillary-source"
        source-layer="sequence"
        paint={{
          'line-color': [
            'step',
            ['get', 'captured_at'],
            '#F77E5E',
            new Date().setFullYear(new Date().getFullYear() - 4),
            '#FFC01B',
            new Date().setFullYear(new Date().getFullYear() - 2),
            '#05CB63',
          ],
          'line-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            10,
            0.7,
            14,
            [
              'case',
              ['>', ['get', 'captured_at'], new Date().setFullYear(new Date().getFullYear() - 2)],
              0.9,
              0.4,
            ],
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 10, 1.5, 14, 2, 14.6, 1.3],
        }}
      />
    </Fragment>
  )
}

export const MapillaryFMCLayers = () => {
  return (
    <Fragment>
      <Source
        id="mapillary-fmc-source"
        type="vector"
        tiles={[
          `https://tiles.mapillary.com/maps/vtp/mly1_public/2/{z}/{x}/{y}?access_token=${apiKeyMapillary}`,
        ]}
        minzoom={0}
        maxzoom={14}
      />
      <Layer
        id="mapillary-fmc-point-click-target"
        type="circle"
        source="mapillary-fmc-source"
        source-layer="image"
        filter={[
          'all',
          ['>=', ['get', 'captured_at'], new Date('2025-01-01').getTime()],
          [
            'any',
            ['==', ['get', 'organization_id'], FMC_ORGANIZATION_ID],
            ['in', ['get', 'creator_id'], ['literal', FMC_CREATOR_IDS]],
          ],
        ]}
        paint={{
          'circle-radius': 10,
          'circle-color': 'transparent',
        }}
      />
      <Layer
        id="mapillary-fmc-point"
        type="circle"
        source="mapillary-fmc-source"
        source-layer="image"
        filter={[
          'all',
          ['>=', ['get', 'captured_at'], new Date('2025-01-01').getTime()],
          [
            'any',
            ['==', ['get', 'organization_id'], FMC_ORGANIZATION_ID],
            ['in', ['get', 'creator_id'], ['literal', FMC_CREATOR_IDS]],
          ],
        ]}
        paint={{
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 0.1, 14.5, 3, 15, 3, 17, 5],
          'circle-blur': 0.5,
          'circle-color': '#9B59B6', // Lila/Purple color for FMC Befahrung
        }}
        beforeId="static-layers-start"
      />
      <Layer
        id="mapillary-fmc-line"
        type="line"
        source="mapillary-fmc-source"
        source-layer="sequence"
        filter={[
          'all',
          ['>=', ['get', 'captured_at'], new Date('2025-01-01').getTime()],
          [
            'any',
            ['==', ['get', 'organization_id'], FMC_ORGANIZATION_ID],
            ['in', ['get', 'creator_id'], ['literal', FMC_CREATOR_IDS]],
          ],
        ]}
        paint={{
          'line-color': '#9B59B6', // Lila/Purple color for FMC Befahrung
          'line-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            10,
            0.7,
            14,
            0.9,
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, 2.5, 10, 2.5, 14, 3.5, 14.6, 2.5],
        }}
        beforeId="static-layers-start"
      />
    </Fragment>
  )
}
