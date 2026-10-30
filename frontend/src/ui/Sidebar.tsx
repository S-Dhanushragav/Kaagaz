import type { CatalogScheme, CheckSummary, Language, UserView } from '../api'
import type { Strings } from '../i18n'
import { Close, Logo, Plus } from './Icons'
import { formatDateTime } from '../casefile'
import { count } from '../counts'

export function Wordmark({ t }: { t: Strings }) {
  return (
    <div className="wordmark">
      <Logo />
      <span className="wordmark-text">{t.appName}</span>
    </div>
  )
}

export default function Sidebar({ t, language, schemes, onNewCheck, onOpenScheme, onClose, user, checks, openCheck,
  onOpenCheck, onLogin }: {
  t: Strings; language: Language; schemes: CatalogScheme[]; onNewCheck: () => void; onOpenScheme: (id: string) => void
  onClose?: () => void; user: UserView | null; checks: CheckSummary[]; openCheck: string | null
  onOpenCheck: (id: string) => void; onLogin: () => void
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
        {!user ? (
          <>
            <p className="sidebar-empty">{t.checksEmpty}</p>
            <button type="button" className="button side-login" onClick={onLogin}>{t.logIn}</button>
          </>
        ) : checks.length === 0 ? <p className="sidebar-empty">{t.checksNone}</p> : (
          <ul className="check-list">
            {checks.map((c) => {
              const head = c.head && (language === 'en' ? c.head.name_en ?? c.head.name_mr : c.head.name_mr ?? c.head.name_en)
              return (
                <li key={c.id}>
                  <button type="button" className={c.id === openCheck ? 'check-link on' : 'check-link'} aria-current={c.id === openCheck}
                    onClick={() => onOpenCheck(c.id)}>
                    <span className="check-date">{formatDateTime(c.created, language)}</span>
                    {head && <span className="check-head">{head}</span>}
                    <span className={c.open_steps ? 'check-open' : 'check-open done'}>
                      {c.open_steps ? count(language, 'stepOpen', c.open_steps) : `✓ ${t.allDone}`}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
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
