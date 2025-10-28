import { parseAsStringLiteral, useQueryState } from 'nuqs'

const sources = ['Production', 'Staging', 'Development'] as const

/**
 * Shared hook for source state management using nuqs
 * Extracts the useQueryState call to avoid prop drilling
 */
export const useSource = () => {
  const [source, setSource] = useQueryState(
    'source',
    parseAsStringLiteral(sources).withDefault('Production'),
  )

  return { source, setSource }
}
