import { useEffect, useRef, useState } from 'react'
import type { Language } from '../api'
import { LANGUAGE_NAMES, LANGUAGES, type Strings } from '../i18n'
import { Chevron, Globe } from './Icons'

// An expandable list: three languages now, more in Phase 11.
export default function LanguageMenu({ t, language, onChange }: { t: Strings; language: Language; onChange: (l: Language) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])

  return (
    <div className="langmenu" ref={root}>
      <button type="button" className="langmenu-button" aria-haspopup="listbox" aria-expanded={open}
        aria-label={`${t.language}: ${LANGUAGE_NAMES[language]}`} onClick={() => setOpen((o) => !o)}>
        <Globe /><span>{LANGUAGE_NAMES[language]}</span><Chevron />
      </button>
      {open && (
        <div className="langmenu-list" role="listbox" aria-label={t.language}>
          {LANGUAGES.map((l) => (
            <button key={l} type="button" role="option" aria-selected={l === language} lang={l}
              className={l === language ? 'langmenu-item selected' : 'langmenu-item'}
              onClick={() => { onChange(l); setOpen(false) }}>
              {LANGUAGE_NAMES[l]}
            </button>
          ))}
          <p className="langmenu-soon">{t.moreLanguagesSoon}</p>
        </div>
      )}
    </div>
  )
}
