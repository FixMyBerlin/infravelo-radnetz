import { z } from 'zod'

export const range = (min: number, max: number) => z.coerce.number().gte(min).lte(max)
