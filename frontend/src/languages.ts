import type { Language } from './api'

// Names as on the (Marathi) documents: Devanagari in Hindi and Marathi, Latin letters in every other language (never a
// machine transliteration: the app is about spellings).
export const devanagariNames = (l: Language): boolean => l === 'hi' || l === 'mr'
