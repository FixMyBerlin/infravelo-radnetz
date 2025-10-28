/**
 * Color Filtering Architecture
 * ============================
 *
 * Flow of data and interactions:
 *
 * User Interaction:
 * 1. User clicks on a legend color
 *    └─> Legend.tsx: toggleColor(layerId, label)
 *
 * State Management:
 * 2. useColorFilters hook updates query state
 *    └─> URL: ?colorFilters={"bikelanesCategory":{"Führung gar nicht erkannt":true}}
 *
 * Filter Generation:
 * 3. Layer component calls useLayerFilter(layerId)
 *    └─> useLayerFilter.ts:
 *        - Gets active colors from useColorFilters
 *        - Gets legend items from LAYER_LEGENDS
 *        - Calls createColorFilter() to generate MapLibre expression
 *
 * 4. createColorFilter combines filter expressions
 *    └─> colorFilterUtils.ts:
 *        - Takes legend items with filterExpression
 *        - Combines active ones with ['any', ...expressions]
 *        - Returns null if all active (optimization)
 *
 * Map Rendering:
 * 5. Layer component receives filter expression
 *    └─> BikelaneCategoryLayer.tsx:
 *        <Layer filter={filter ?? undefined} />
 *
 * 6. MapLibre GL applies filter
 *    └─> Only features matching the filter are rendered
 *
 *
 * Component Hierarchy:
 *
 * App.tsx
 *  ├─> Legend (for each active layer)
 *  │    └─> useColorFilters() for toggle state
 *  │
 *  └─> Map
 *       └─> Layer Components (BikelaneCategoryLayer, etc.)
 *            └─> useLayerFilter(layerId)
 *                 ├─> useColorFilters() for active colors
 *                 ├─> LAYER_LEGENDS[layerId] for legend items
 *                 └─> createColorFilter() to generate expression
 *
 *
 * Data Flow:
 *
 * Legend Items (legendStyle.ts)
 *  {
 *    color: '#FF0000',
 *    label: 'Red items',
 *    filterExpression: ['==', ['get', 'category'], 'red']
 *  }
 *           ↓
 * Active Colors (useColorFilters)
 *  ['Red items']
 *           ↓
 * MapLibre Filter (createColorFilter)
 *  ['==', ['get', 'category'], 'red']
 *           ↓
 * Rendered Features (MapLibre GL)
 *  Only features where category === 'red'
 */

export {}
