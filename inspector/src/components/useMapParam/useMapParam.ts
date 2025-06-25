import { createParser, useQueryState } from 'nuqs'
import { parseMapParam, serializeMapParam } from './mapParam.js'
import { mapParamFallback } from './mapParamFallback.js'


const mapParamParser = createParser({
  parse: (query) => parseMapParam(query),
  serialize: (object) => serializeMapParam(object),
})
  .withOptions({ history: 'push' })
  .withDefault({
    zoom: mapParamFallback.zoom,
    lat: mapParamFallback.lat,
    lng: mapParamFallback.lng,
  })

export const useMapParam = () => {
  const [mapParam, setMapParam] = useQueryState('map', mapParamParser)
  return { mapParam, setMapParam }
}
