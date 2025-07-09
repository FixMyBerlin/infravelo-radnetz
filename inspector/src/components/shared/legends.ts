import { getAgeLegend } from './ageBasedStyle'
import { getCyclewayNoLayerLegend } from './cyclewayNoStyle'
import { getDualCarrigewayLegend } from './dualCarrigewayStyle'
import { getMapillaryLegend } from './mapillaryStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'
import { getSurfaceColorLegend } from './surfaceColorStyle'
import { getSurfaceSettLegend } from './surfaceSettStyle'
import { getTrafficSignLegend } from './trafficSignStyle'

export const LAYER_LEGENDS = {
  bikelanesAge: getAgeLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  bikelanesSurface: getSurfaceSettLegend(),
  bikelanesSurfaceColor: getSurfaceColorLegend(),
  bikelanesTrafficSign: getTrafficSignLegend(),
  bikelanesMapillary: getMapillaryLegend(),
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsSurface: getSurfaceSettLegend(),
  roadsCyclewayNo: getCyclewayNoLayerLegend(),
  roadDualCarriageway: getDualCarrigewayLegend(),
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
  roadsPathSurface: getSurfaceSettLegend(),
}
