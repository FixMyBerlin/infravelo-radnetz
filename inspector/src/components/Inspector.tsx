import { TableCellsIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { clsx } from 'clsx'
import { formatDistanceToNow, fromUnixTime } from 'date-fns'
import { useState } from 'react'
import type { MapGeoJSONFeature } from 'react-map-gl/maplibre'

const longOsmType = {
  W: 'way',
  N: 'node',
  R: 'relation',
  w: 'way',
  n: 'node',
  r: 'relation',
  // Just so we can use this for both format
  way: 'way',
  node: 'node',
  relation: 'relation',
}

type LayerConfig = {
  id: string
  source: string
  inspectorHighlightTags?: readonly string[]
}

type Props = {
  inspectorFeatures: MapGeoJSONFeature[]
  activeLayerConfigs: LayerConfig[]
}

export const Inspector = ({ inspectorFeatures, activeLayerConfigs }: Props) => {
  const [open, setOpen] = useState(true)

  if (!open) {
    return (
      <button
        className="absolute top-4 right-4 z-50 cursor-pointer rounded-full bg-white p-2 shadow hover:bg-blue-200"
        onClick={() => setOpen(true)}
        aria-label="Show sidebar"
      >
        <TableCellsIcon className="h-6 w-6 text-gray-700" />
      </button>
    )
  }

  return (
    <aside className="relative h-full w-80 max-w-xs border-l border-gray-200 bg-white shadow-lg">
      <article className="overflow-y-auto p-4 text-sm">
        <button
          className="absolute top-4 right-4 z-10 cursor-pointer rounded-full bg-white p-1 hover:bg-blue-200"
          onClick={() => setOpen(false)}
          aria-label="Close sidebar"
        >
          <XMarkIcon className="h-5 w-5 text-gray-700" />
        </button>
        <h2 className="mb-4 font-bold">Inspector</h2>
        {inspectorFeatures.length > 0 ? (
          <div className="mb-4">
            {inspectorFeatures.map((feature, index) => {
              const urlPart =
                feature.properties.osm_type && feature.properties.osm_id
                  ? // @ts-expect-error properties are not typed…
                    `${longOsmType[feature.properties.osm_type]}/${feature.properties.osm_id}`
                  : feature.properties.id
              return (
                <section key={index} className="mb-4">
                  <div className="mb-1 flex items-center justify-between border-b border-b-gray-300 pb-1">
                    <h3 className="font-bold">{feature.sourceLayer}</h3>
                    <div className="flex items-center gap-2">
                      <a
                        href={`https://www.openstreetmap.org/${urlPart}/history`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs whitespace-nowrap text-blue-500 hover:underline"
                      >
                        OSM
                      </a>
                      {feature.properties.osm_id && (
                        <a
                          href={`https://tilda-geo.de/regionen/infravelo?map=15/${
                            getWayCoordinates(feature).center.lat
                          }/${
                            getWayCoordinates(feature).center.lng
                          }&config=l6jzgk.5mct1h.4&v=2&data=radverkehrsnetz-vorrangnetz-mask&f=10|way/${feature.properties.osm_id}|${
                            getWayCoordinates(feature).bbox.lng1
                          }|${getWayCoordinates(feature).bbox.lat1}|${
                            getWayCoordinates(feature).bbox.lng2
                          }|${getWayCoordinates(feature).bbox.lat2}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs whitespace-nowrap text-blue-500 hover:underline"
                        >
                          TILDA
                        </a>
                      )}
                      {feature.properties.changeset_id && (
                        <>
                          <a
                            href={`https://www.openstreetmap.org/changeset/${feature.properties.changeset_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs whitespace-nowrap text-blue-500 hover:underline"
                          >
                            Changeset
                          </a>
                          <a
                            href={`https://osmcha.org/changesets/${feature.properties.changeset_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs whitespace-nowrap text-blue-500 hover:underline"
                          >
                            OSMCha
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                  <ul className="space-y-0.5">
                    {Object.entries(feature.properties)
                      .sort(([keyA], [keyB]) => {
                        if (keyA === 'id') return -1
                        if (keyB === 'id') return 1
                        return keyA.localeCompare(keyB)
                      })
                      .map(([key, value]) => {
                        const highlightKey = activeLayerConfigs.some((config) =>
                          config.inspectorHighlightTags?.includes(key),
                        )
                        return (
                          <li
                            key={key}
                            className={clsx(
                              'group flex flex-col',
                              highlightKey ? 'bg-yellow-100 ring-4 ring-yellow-100' : '',
                            )}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex gap-2">
                                <strong className="inline-block min-w-20 font-semibold">
                                  {key}:
                                </strong>{' '}
                                <div>
                                  {typeof value === 'boolean' ? value.toString() : value}

                                  <div className="text-xs text-gray-500">
                                    <>
                                      {key == 'updated_at' ? (
                                        <>{formatDistanceToNow(fromUnixTime(Number(value)))} ago </>
                                      ) : null}
                                      {key.includes('mapillary') && key != 'mapillary_coverage' ? (
                                        <a
                                          href={`https://www.mapillary.com/app/?z=17&pKey=${value}&focus=photo`}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-xs text-blue-500 hover:underline"
                                        >
                                          Mapillary
                                        </a>
                                      ) : null}
                                    </>
                                  </div>
                                </div>
                              </div>
                              <span
                                className="invisible text-xs text-gray-500 group-hover:visible"
                                title={
                                  typeof value === 'boolean'
                                    ? 'boolean'
                                    : typeof value === 'number'
                                      ? 'number'
                                      : 'string'
                                }
                              >
                                {typeof value === 'boolean'
                                  ? 'b'
                                  : typeof value === 'number'
                                    ? 'n'
                                    : 's'}
                              </span>
                            </div>
                          </li>
                        )
                      })}
                  </ul>
                  <details className="font-xs">
                    <summary className="cursor-pointer hover:underline">Raw</summary>
                    <pre>{JSON.stringify(feature, undefined, 2)}</pre>
                  </details>
                </section>
              )
            })}
          </div>
        ) : (
          <p>No features selected.</p>
        )}
      </article>
    </aside>
  )
}

// Get the coordinates needed for the TILDA URL
const getWayCoordinates = (feature: MapGeoJSONFeature) => {
  if (feature.geometry.type === 'LineString') {
    const coords = feature.geometry.coordinates as [number, number][]
    const firstCoord = coords[0]
    const lastCoord = coords[coords.length - 1]
    return {
      center: {
        lng: firstCoord[0],
        lat: firstCoord[1],
      },
      bbox: {
        lng1: firstCoord[0],
        lat1: firstCoord[1],
        lng2: lastCoord[0],
        lat2: lastCoord[1],
      },
    }
  }

  // This project only has LineStrings, but provide a fallback just in case
  return {
    center: { lng: 13.367, lat: 52.507 },
    bbox: { lng1: 13.367, lat1: 52.507, lng2: 13.367, lat2: 52.507 },
  }
}
