import { parseAsArrayOf, parseAsString, useQueryState } from 'nuqs'

const CONTEXT_DEFAULTS: readonly string[] = []

/**
 * Shared hook for managing context layer state in URL
 * Used across all context layer components for consistent state management
 */
export const useContextLayers = () => {
  const [contextLayers, setContextLayers] = useQueryState(
    'context_layer',
    parseAsArrayOf(parseAsString).withDefault([...CONTEXT_DEFAULTS]),
  )

  const toggle = (key: string) => {
    setContextLayers((prev) =>
      prev.includes(key) ? prev.filter((v) => v !== key) : [...prev, key],
    )
  }

  const isActive = (key: string) => contextLayers.includes(key)

  return {
    contextLayers,
    setContextLayers,
    toggle,
    isActive,
  }
}
