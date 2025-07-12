export type CategoryId = (typeof categories)[number]['id']

export const categories = [
  // Bike lanes and their variants
  { id: 'bikelanes', source: 'bikelanes' },
  { id: 'bikelanesCategory', source: 'bikelanes', inspectorHighlightTags: ['category'] },
  {
    id: 'bikelanesBufferMarking',
    source: 'bikelanes',
    inspectorHighlightTags: [
      'category',
      'buffer_right',
      'buffer_left',
      'buffer_both',
      'marking_right',
      'marking_left',
      'marking_both',
      'separation_right',
      'separation_left',
      'separation_both',
    ],
  },
  { id: 'bikelanesAge', source: 'bikelanes', inspectorHighlightTags: ['updated_at'] },
  { id: 'bikelanesOneway', source: 'bikelanes', inspectorHighlightTags: ['oneway', 'oneway_bike'] },
  {
    id: 'bikelanesSurface',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface'],
  },
  {
    id: 'bikelanesWidth',
    source: 'bikelanes',
    inspectorHighlightTags: ['width', 'width_source', 'category'],
  },
  {
    id: 'bikelanesSurfaceColor',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface_color'],
  },
  {
    id: 'bikelanesTrafficSign',
    source: 'bikelanes',
    inspectorHighlightTags: ['traffic_sign'],
  },
  {
    id: 'bikelanesMapillary',
    source: 'bikelanes',
    inspectorHighlightTags: [
      'mapillary',
      'mapillary_left',
      'mapillary_right',
      'mapillary_traffic_sign',
      'traffic_sign',
    ],
  },
  {
    id: 'bikelanesUpdateSource',
    source: 'bikelanes',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
  },

  // Roads and their variants
  { id: 'roads', source: 'roads' },
  { id: 'roadsAge', source: 'roads' },
  { id: 'roadsOneway', source: 'roads' },
  { id: 'roadsSurface', source: 'roads' },
  { id: 'roadsCyclewayNo', source: 'roads' },
  { id: 'roadDualCarriageway', source: 'roads' },
  {
    id: 'roadsUpdateSource',
    source: 'roads',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
  },

  // Road paths and their variants
  { id: 'roadsPath', source: 'roadsPathClasses' },
  { id: 'roadsPathAge', source: 'roadsPathClasses' },
  { id: 'roadsPathOneway', source: 'roadsPathClasses' },
  { id: 'roadsPathSurface', source: 'roadsPathClasses' },
  {
    id: 'roadsPathsUpdateSource',
    source: 'roadsPathClasses',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
  },
] as const
