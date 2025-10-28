import { useContextLayers } from '../hooks/useContextLayers'
import { Legend } from './Legend'
import { getOsmUpdateContextLegend } from './shared/legends'

type Props = {
  isLoading?: boolean
}

export const OsmUpdateContextControls = ({ isLoading = false }: Props) => {
  const { isActive, toggle } = useContextLayers()

  return (
    <>
      <li>
        <label className="flex w-full items-center gap-2">
          <input
            type="checkbox"
            checked={isActive('osm_update_status')}
            onChange={() => toggle('osm_update_status')}
            disabled={isLoading}
          />
          OSM-Update Status
          {isLoading && <span className="text-xs text-gray-500">(Lade...)</span>}
        </label>
      </li>
      {isActive('osm_update_status') && <Legend legend={getOsmUpdateContextLegend()} />}
    </>
  )
}
