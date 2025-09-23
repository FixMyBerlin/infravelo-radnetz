export const mapillaryKeyUrl = (key: number | string | undefined) => {
  if (!key) return undefined
  return `https://www.mapillary.com/app/?pKey=${key}&focus=photo&z=15`
}
