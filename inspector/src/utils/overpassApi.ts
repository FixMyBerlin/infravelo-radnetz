type OsmElementType = 'node' | 'way' | 'relation'

type OsmElement = {
  type: OsmElementType
  id: number
  timestamp: string
  user: string
  changeset: number
}

type OsmElementGroup = {
  nodes: number[]
  ways: number[]
  relations: number[]
}

/**
 * Groups OSM IDs by their type for efficient batch querying
 */
export const groupOsmIdsByType = (
  osmIds: Array<{ osmId: number; osmType: string }>,
): OsmElementGroup => {
  const groups: OsmElementGroup = {
    nodes: [],
    ways: [],
    relations: [],
  }

  for (const { osmId, osmType } of osmIds) {
    const normalizedType = osmType.toLowerCase()
    if (normalizedType === 'n' || normalizedType === 'node') {
      groups.nodes.push(osmId)
    } else if (normalizedType === 'w' || normalizedType === 'way') {
      groups.ways.push(osmId)
    } else if (normalizedType === 'r' || normalizedType === 'relation') {
      groups.relations.push(osmId)
    }
  }

  return groups
}

/**
 * Builds an Overpass API query for batch fetching OSM elements
 */
export const buildOverpassQuery = (groups: OsmElementGroup): string => {
  const queries: string[] = []

  if (groups.nodes.length > 0) {
    queries.push(`node(id:${groups.nodes.join(',')});`)
  }
  if (groups.ways.length > 0) {
    queries.push(`way(id:${groups.ways.join(',')});`)
  }
  if (groups.relations.length > 0) {
    queries.push(`relation(id:${groups.relations.join(',')});`)
  }

  if (queries.length === 0) {
    return ''
  }

  return `[out:json][timeout:25];
(
  ${queries.join('\n  ')}
);
out meta;`
}

/**
 * Fetches OSM element metadata from Overpass API
 */
export const fetchOsmElements = async (
  osmIds: Array<{ osmId: number; osmType: string }>,
): Promise<Record<number, OsmElement>> => {
  if (osmIds.length === 0) {
    return {}
  }

  const groups = groupOsmIdsByType(osmIds)
  const query = buildOverpassQuery(groups)

  if (!query) {
    return {}
  }

  try {
    const response = await fetch('https://overpass-api.de/api/interpreter', {
      method: 'POST',
      headers: {
        'Content-Type': 'text/plain',
      },
      body: query,
    })

    if (!response.ok) {
      throw new Error(`Overpass API error: ${response.status} ${response.statusText}`)
    }

    const data = await response.json()

    if (data.error) {
      throw new Error(`Overpass API error: ${data.error}`)
    }

    // Convert array to map keyed by OSM ID
    const elementsMap: Record<number, OsmElement> = {}

    for (const element of data.elements || []) {
      elementsMap[element.id] = {
        type: element.type,
        id: element.id,
        timestamp: element.timestamp,
        user: element.user,
        changeset: element.changeset,
      }
    }

    return elementsMap
  } catch (error) {
    console.error('Failed to fetch OSM elements from Overpass API:', error)
    throw error
  }
}
