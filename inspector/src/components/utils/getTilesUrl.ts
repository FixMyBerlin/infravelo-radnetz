
const tilesBaseUrl = {
  development: 'http://localhost:3000',
  staging: 'https://staging-tiles.tilda-geo.de',
  production: 'https://tiles.tilda-geo.de',
}
export type ENV = keyof typeof tilesBaseUrl

export const getTilesUrl = (path: string, envKey: ENV) => {
  const base = tilesBaseUrl[envKey]
  return path ? `${base}${path}` : base
}
