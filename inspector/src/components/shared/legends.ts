import { getAgeLegend } from './ageBasedStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'

export const LAYER_LEGENDS = {
  bikelanesAge: getAgeLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
}
