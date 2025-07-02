import { parseAsArrayOf, parseAsString, useQueryState } from 'nuqs'



export const useDataParam = () => {
  const [DataParam, setDataParam] = useQueryState(
    'data',
    parseAsArrayOf(parseAsString).withDefault([]),
  )
  return { DataParam, setDataParam }
}
