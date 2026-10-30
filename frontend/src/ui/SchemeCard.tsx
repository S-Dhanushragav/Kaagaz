import { useEffect, useRef } from 'react'
import type { CatalogLine, CatalogScheme } from '../api'
import type { Strings } from '../i18n'
import { Close, Link } from './Icons'

function Line({ t, line }: { t: Strings; line: CatalogLine }) {
  return (
    <li className="rule-line">
      <span className="rule-text">{line.text}</span>
      <span className="rule-meta">
        {line.status !== 'verified' && <span className={`badge ${line.status}`}>{t.status[line.status]}</span>}
        {line.sources.map((s) => s.url
          ? <a key={s.url} className="source-chip" href={s.url} target="_blank" rel="noreferrer">{s.source}<Link /></a>
          : <span key={s.source} className="source-chip plain">{s.source}</span>)}
      </span>
    </li>
  )
}

// A scheme's rules from the verified YAML (GET /schemes), as a dialog.
export default function SchemeCard({ t, scheme, onClose }: { t: Strings; scheme: CatalogScheme; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal()
  }, [])
  const checked = [...scheme.rules, ...scheme.other_proof].map((l) => l.last_checked).sort().at(-1)
  return (
    <dialog ref={ref} className="scheme-card" aria-labelledby="scheme-title" onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) ref.current?.close() }}>
      <div className="scheme-card-inner">
        <header className="scheme-card-head">
          <div>
            <p className="eyebrow">{t.schemesTitle}</p>
            <h2 id="scheme-title">{scheme.name}</h2>
          </div>
          <button type="button" className="icon-button" aria-label={t.close} onClick={() => ref.current?.close()}><Close /></button>
        </header>
        <p className="benefit"><span className="eyebrow">{t.benefit}</span>
          <span className="benefit-text">{scheme.benefit.text}</span>
          <span className="rule-meta">
            {scheme.benefit.status !== 'verified' && <span className={`badge ${scheme.benefit.status}`}>{t.status[scheme.benefit.status]}</span>}
            {scheme.benefit.sources.map((s) => s.url
              ? <a key={s.url} className="source-chip" href={s.url} target="_blank" rel="noreferrer">{s.source}<Link /></a>
              : <span key={s.source} className="source-chip plain">{s.source}</span>)}
          </span>
        </p>
        <h3>{t.whoFor}</h3>
        <ul className="rule-lines">{scheme.rules.map((l) => <Line key={l.rule_id} t={t} line={l} />)}</ul>
        {scheme.other_proof.length > 0 && (
          <>
            <h3>{t.alsoAsked}</h3>
            <ul className="rule-lines">{scheme.other_proof.map((l) => <Line key={l.rule_id} t={t} line={l} />)}</ul>
          </>
        )}
        <p className="scheme-note">{t.schemeNote}{checked && <> {t.lastChecked}: {checked}.</>}</p>
      </div>
    </dialog>
  )
}
