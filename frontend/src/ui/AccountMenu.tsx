import { useEffect, useRef, useState } from 'react'
import { deleteMe, type Language, type UserView } from '../api'
import { LANGUAGE_NAMES, LANGUAGES, type Strings } from '../i18n'
import { Chevron, Person } from './Icons'

// The logged-in account: number ending, language, log out, and "Delete my data" (with a confirmation).
export default function AccountMenu({ t, user, language, onLanguage, onLogout, onDeleted }: {
  t: Strings; user: UserView; language: Language; onLanguage: (l: Language) => void
  onLogout: () => void; onDeleted: () => void
}) {
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])

  useEffect(() => {
    if (confirming && dialog.current && !dialog.current.open) dialog.current.showModal()
  }, [confirming])

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await deleteMe()
      dialog.current?.close()
      onDeleted()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div className="account" ref={root}>
      <button type="button" className="account-button" aria-haspopup="menu" aria-expanded={open}
        aria-label={`${t.account}: ${t.ending.replace('{last4}', user.phone_last4)}`} onClick={() => setOpen((o) => !o)}>
        <Person /><span className="account-last4">••{user.phone_last4}</span><Chevron />
      </button>
      {open && (
        <div className="account-list" role="menu">
          <p className="account-who">{t.ending.replace('{last4}', user.phone_last4)}</p>
          <p className="eyebrow">{t.language}</p>
          <div className="account-langs" role="group" aria-label={t.language}>
            {LANGUAGES.map((l) => (
              <button key={l} type="button" lang={l} aria-pressed={l === language}
                className={l === language ? 'chip on' : 'chip'} onClick={() => onLanguage(l)}>{LANGUAGE_NAMES[l]}</button>
            ))}
          </div>
          <button type="button" role="menuitem" className="langmenu-item" onClick={() => { setOpen(false); onLogout() }}>{t.logOut}</button>
          <button type="button" role="menuitem" className="langmenu-item danger-text"
            onClick={() => { setOpen(false); setConfirming(true) }}>{t.deleteData}</button>
        </div>
      )}
      {confirming && (
        <dialog ref={dialog} className="confirm" aria-labelledby="delete-title" onClose={() => { setConfirming(false); setBusy(false) }}>
          <h2 id="delete-title">{t.deleteTitle}</h2>
          <p>{t.deleteText}</p>
          {error && <p className="alert" role="alert">{error}</p>}
          <div className="button-row">
            <button type="button" className="button primary danger" disabled={busy} onClick={() => void remove()}>{t.deleteYes}</button>
            <button type="button" className="button" disabled={busy} onClick={() => dialog.current?.close()}>{t.cancel}</button>
          </div>
        </dialog>
      )}
    </div>
  )
}
