import type { StyleImageMetadata } from 'maplibre-gl'
import { useMap } from 'react-map-gl/maplibre'

type Props = { name: string; url: string; sdf: StyleImageMetadata['sdf'] }

export const AddMapImage = ({ name, url, sdf }: Props) => {
  const { current: map } = useMap()
  if (!map) return null
  if (map.hasImage(name)) return null

  map.loadImage(url).then(({ data }) => {
    if (!map.hasImage(name)) {
      map.addImage(name, data, { sdf })
    }
  })

  return null
}
