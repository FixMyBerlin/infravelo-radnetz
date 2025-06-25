import { TableCellsIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { formatDistanceToNow, parseISO } from 'date-fns'
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

type Props = {
  inspectorFeatures: MapGeoJSONFeature[]
}

export const Inspector = ({ inspectorFeatures }: Props) => {
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
                    <a
                      href={`https://www.openstreetmap.org/${urlPart}/history`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs whitespace-nowrap text-blue-500 hover:underline"
                    >
                      OSM
                    </a>
                  </div>
                  <ul className="space-y-0.5">
                    {Object.entries(feature.properties)
                      .sort(([keyA], [keyB]) => {
                        if (keyA === 'id') return -1
                        if (keyB === 'id') return 1
                        return keyA.localeCompare(keyB)
                      })
                      .map(([key, value]) => (
                        <li key={key} className="group flex flex-col">
                          <div className="flex items-center justify-between">
                            <div className="flex gap-2">
                              <strong className="inline-block min-w-20 font-semibold">
                                {key}:
                              </strong>{' '}
                              <div>
                                {typeof value === 'boolean' ? value.toString() : value}

                                {key.endsWith('_at') && typeof value === 'string' && (
                                  <div className="text-xs text-gray-500">
                                    {formatDistanceToNow(parseISO(value))} ago
                                  </div>
                                )}
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
                      ))}
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
