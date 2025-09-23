import { ArrowTopRightOnSquareIcon } from '@heroicons/react/24/outline'
import type { MapGeoJSONFeature } from 'react-map-gl/maplibre'
import { mapillaryKeyUrl } from '../utils/mapillary'

type Props = {
  feature: MapGeoJSONFeature
}

export const MapillaryPreview = ({ feature }: Props) => {
  const pKey = feature.properties.id || feature.properties.image_id

  if (!pKey) {
    return null
  }

  const isMapillary = feature.properties.creator_id
  if (!isMapillary) {
    return null
  }

  const link = mapillaryKeyUrl(pKey)

  return (
    <div className="mt-4">
      <h3 className="mb-2 font-semibold">Mapillary Vorschau</h3>
      <div className="mb-2">
        <span className="text-sm font-medium text-gray-700">pKey: </span>
        <code className="rounded bg-gray-100 px-2 py-1 font-mono text-sm text-gray-900">
          {pKey}
        </code>
      </div>
      <section>
        <iframe
          title="Mapillary Image Preview"
          src={`https://www.mapillary.com/embed?image_key=${pKey}&style=photo`}
          className="aspect-square w-full rounded border"
        />
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 flex items-center gap-1 text-xs text-blue-500 hover:underline"
          >
            <ArrowTopRightOnSquareIcon className="h-3 w-3" />
            In neuem Fenster öffnen…
          </a>
        )}
      </section>
    </div>
  )
}
