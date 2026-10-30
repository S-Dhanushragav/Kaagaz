import type { CatalogScheme } from '../api'
import type { Strings } from '../i18n'
import { Close, Logo, Plus } from './Icons'

export function Wordmark({ t }: { t: Strings }) {
  return (
    <div className="wordmark">
      <Logo />
      <span className="wordmark-text">{t.appName}</span>
    </div>
  )
}

export default function Sidebar({ t, schemes, onNewCheck, onOpenScheme, onClose }: {
  t: Strings; schemes: CatalogScheme[]; onNewCheck: () => void; onOpenScheme: (id: string) => void; onClose?: () => void
}) {
  return (
    <nav className="sidebar" aria-label={t.menu}>
      <div className="sidebar-head">
        <Wordmark t={t} />
        {onClose && <button type="button" className="icon-button only-mobile" aria-label={t.close} onClick={onClose}><Close /></button>}
      </div>
      <p className="demo-note">{t.demoNote}</p>
      <button type="button" className="button primary new-check" onClick={onNewCheck}><Plus />{t.newCheck}</button>

      <section className="sidebar-section">
        <h2 className="eyebrow">{t.yourChecks}</h2>
        {/* Phase 9 fills this from the login-based history API. */}
        <p className="sidebar-empty">{t.checksEmpty}</p>
      </section>

      <section className="sidebar-section">
        <h2 className="eyebrow">{t.schemesTitle}</h2>
        <ul className="scheme-list">
          {schemes.map((s) => (
            <li key={s.id}>
              <button type="button" className="scheme-link" onClick={() => onOpenScheme(s.id)}>
                <span className="scheme-link-name">{s.name}</span>
                <span className="scheme-link-sub">{s.benefit.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <p className="sidebar-foot">{t.specimen}</p>
    </nav>
  )
}
