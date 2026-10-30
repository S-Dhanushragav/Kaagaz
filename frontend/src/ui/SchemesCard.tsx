import { useEffect, useState, type ReactNode } from 'react'
import type { CatalogScheme, Language, SchemeResult, SessionView } from '../api'
import { count } from '../counts'
import type { Strings } from '../i18n'
import { detailReasons, memberName, OUTCOME_MARK, sources } from '../labels'
import { Close, Office } from './Icons'

const OUTCOMES: SchemeResult['outcome'][] = ['eligible_on_documents', 'blocked_by_issues', 'check_at_office', 'not_eligible']

// "Schemes for your family", part of the result message: members x schemes, coloured and marked by outcome; tap a
// box for the reasons (below the matrix on wide screens, a bottom sheet on phones). Then the plan's office visits.
export default function SchemesCard({ t, view, language, schemes, narrow, onOpenScheme }: {
  t: Strings; view: SessionView; language: Language; schemes: CatalogScheme[]; narrow: boolean
  onOpenScheme: (id: string) => void
}) {
  const [picked, setPicked] = useState<{ member: string; scheme: string } | null>(null)
  const hh = view.household
  const results = view.results ?? []
  if (!hh || !results.length) return null
  const columns = schemes.length ? schemes.map((s) => ({ id: s.id, name: s.name, short: s.short }))
    : [...new Map(results.map((r) => [r.scheme_id, { id: r.scheme_id, name: r.scheme_name, short: r.scheme_name }])).values()]
  const result = (m: string, s: string) => results.find((r) => r.member_id === m && r.scheme_id === s)
  const chosen = picked ? result(picked.member, picked.scheme) : undefined
  const chosenMember = picked ? hh.members.find((m) => m.member_id === picked.member) : undefined
  const detail = chosen && chosenMember && (
    <Detail t={t} result={chosen} reasons={detailReasons(view, chosen, language, t)} who={memberName(chosenMember, language, t)}
      scheme={columns.find((c) => c.id === chosen.scheme_id)?.name ?? chosen.scheme_id} />
  )

  return (
    <section className="card-block schemes-card" aria-labelledby="schemes-title">
      <header className="card-head"><h2 id="schemes-title">{t.matrixTitle}</h2></header>
      <table className="matrix">
        <colgroup><col className="member-col" />{columns.map((c) => <col key={c.id} />)}</colgroup>
        <thead>
          <tr>
            <td />
            {columns.map((c) => (
              <th key={c.id} scope="col">
                <button type="button" className="matrix-scheme" title={c.name} onClick={() => onOpenScheme(c.id)}>{c.short}</button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hh.members.map((m) => (
            <tr key={m.member_id}>
              <th scope="row" className="matrix-member">
                {memberName(m, language, t)}
                {!m.on_ration_card && <span className="tag">{t.notOnCard}</span>}
              </th>
              {columns.map((c) => {
                const r = result(m.member_id, c.id)
                if (!r) return <td key={c.id} />
                const on = picked?.member === m.member_id && picked.scheme === c.id
                return (
                  <td key={c.id}>
                    <button type="button" className={`cell ${r.outcome}${on ? ' on' : ''}`} aria-pressed={on}
                      aria-label={`${memberName(m, language, t)}, ${c.name}: ${t.outcomes[r.outcome]}`}
                      onClick={() => setPicked(on ? null : { member: m.member_id, scheme: c.id })}>
                      {OUTCOME_MARK[r.outcome]}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="legend">
        {OUTCOMES.map((o) => <li key={o}><span className={`cell mini ${o}`} aria-hidden="true">{OUTCOME_MARK[o]}</span>{t.outcomes[o]}</li>)}
      </ul>
      {detail && !narrow ? detail : <p className="hint">{t.tapForReasons}</p>}
      {detail && narrow && <Sheet t={t} onClose={() => setPicked(null)}>{detail}</Sheet>}
      <Visits t={t} view={view} language={language} />
    </section>
  )
}

function Detail({ t, result, reasons, who, scheme }: {
  t: Strings; result: SchemeResult; reasons: string[]; who: string; scheme: string
}) {
  return (
    <div className={`reasons ${result.outcome}`} aria-live="polite">
      <p className="reasons-title"><strong>{who}</strong> · {scheme}</p>
      <p className="reasons-outcome">
        <span className={`cell mini ${result.outcome}`} aria-hidden="true">{OUTCOME_MARK[result.outcome]}</span>
        {t.outcomes[result.outcome]}
      </p>
      <ul>{reasons.map((x, n) => <li key={n}>{x}</li>)}</ul>
      {(result.display?.warnings ?? []).length > 0 && (
        <ul className="warnings">{result.display!.warnings.map((x, n) => <li key={n}>{x}</li>)}</ul>
      )}
      {sources(result).length > 0 && (
        <p className="reasons-sources">{t.sources}: {sources(result).map(([url, source]) => (
          <a key={url} href={url} target="_blank" rel="noreferrer">{source}</a>
        ))}</p>
      )}
    </div>
  )
}

// Phones: the reasons for one box, over the chat. Escape, the close button or the scrim closes it.
function Sheet({ t, onClose, children }: { t: Strings; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [onClose])
  return (
    <>
      <div className="scrim sheet-scrim" onClick={onClose} aria-hidden="true" />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={t.matrixTitle}>
        <div className="sheet-head">
          <span className="sheet-handle" aria-hidden="true" />
          <button type="button" className="icon-button" aria-label={t.close} onClick={onClose}><Close /></button>
        </div>
        {children}
      </div>
    </>
  )
}

function Visits({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const steps = view.plan?.steps ?? []
  const visits = new Map<number, number[]>()
  steps.forEach((s, i) => { if (s.kind === 'fix' && s.visit) visits.set(s.visit, [...(visits.get(s.visit) ?? []), i]) })
  if (!visits.size) return null
  return (
    <section className="visits">
      <h3>{t.officeVisits}</h3>
      <ol>
        {[...visits.entries()].sort(([a], [b]) => a - b).map(([visit, idx]) => {
          const office = view.speech?.[idx[0]]?.display?.office
          return (
            <li key={visit}>
              <span className="visit-num" aria-hidden="true">{visit}</span>
              <span className="visit-body">
                <span className="visit-office"><Office size={18} />{office ? office.text : `${t.visit} ${visit}`}
                  {office && !office.verified && <span className="unverified"> ({t.unverified})</span>}</span>
                <span className="visit-steps">{count(language, 'step', idx.length)}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
