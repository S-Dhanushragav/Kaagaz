// Tamil, Telugu and Kannada text uses Noto Sans for that script (public/fonts, SIL Open Font License), fetched only
// when the family picks that language: nobody else downloads it. Until it arrives (or if it cannot), the phone's own
// font for the script is used (font-display: swap).
import type { Language } from './api'

const FONTS: Partial<Record<Language, string>> = { ta: 'Noto Sans Tamil', te: 'Noto Sans Telugu', kn: 'Noto Sans Kannada' }
const requested = new Set<string>()

export function loadScriptFont(language: Language): void {
  const family = FONTS[language]
  if (!family || requested.has(family) || typeof FontFace === 'undefined') return
  requested.add(family)
  const face = new FontFace(family, `url(/fonts/${family.replace(/ /g, '')}.woff2) format('woff2')`,
    { weight: '400 700', display: 'swap' })
  face.load().then((f) => document.fonts.add(f)).catch(() => { requested.delete(family) })
}
