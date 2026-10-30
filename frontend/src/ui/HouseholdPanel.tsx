import { useState } from 'react'
import type { CatalogScheme, Language, SchemeResult, SessionView } from '../api'
import type { Strings } from '../i18n'
import { memberName, OUTCOME_MARK, sources } from '../labels'
import { Close, Office } from './Icons'

const OUTCOMES: SchemeResult['outcome'][] = ['eligible_on_documents', 'blocked_by_issues', 'check_at_office', 'not_eligible']

// Members x schemes, coloured and marked by outcome; tap a box for the reasons. Below: the plan's office visits.
export default function HouseholdPanel({ t, view, language, schemes, onOpenScheme, onClose }: {
  t: Strings; view: SessionView | null; language: Language; schemes: CatalogScheme[]
  onOpenScheme: (id: string) => void; onClose?: () => void
}) {
  const [picked, setPicked] = useState<{ member: string; scheme: string } | null>(null)
  const hh = view?.household
  const results = view?.results ?? []
  const columns = schemes.length ? schemes.map((s) => ({ id: s.id, name: s.name, short: s.short }))
    : [...new Map(results.map((r) => [r.scheme_id, { id: r.scheme_id, name: r.scheme_name, short: r.scheme_name }])).values()]
  const result = (m: string, s: string) => results.find((r) => r.member_id === m && r.scheme_id === s)
  const chosen = picked ? result(picked.member, picked.scheme) : undefined
  const chosenMember = picked ? hh?.members.find((m) => m.member_id === picked.member) : undefined

  return (
    <div className="panel-inner">
      <header className="panel-head">
        <h2>{view ? t.matrixTitle : t.howTitle}</h2>
        {onClose && <button type="button" className="icon-button" aria-label={t.close} onClick={onClose}><Close /></button>}
      </header>
      {!hh || !results.length ? (view ? <p className="panel-empty">{t.panelEmpty}</p> : <HowItWorks t={t} />) : (
        <>
          <div className="matrix-wrap">
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
          </div>
          <ul className="legend">
            {OUTCOMES.map((o) => <li key={o}><span className={`cell mini ${o}`} aria-hidden="true">{OUTCOME_MARK[o]}</span>{t.outcomes[o]}</li>)}
          </ul>
          {chosen && chosenMember ? (
            <div className={`reasons ${chosen.outcome}`} aria-live="polite">
              <p className="reasons-title">
                <strong>{memberName(chosenMember, language, t)}</strong> · {columns.find((c) => c.id === chosen.scheme_id)?.name}
              </p>
              <p className="reasons-outcome">{OUTCOME_MARK[chosen.outcome]} {t.outcomes[chosen.outcome]}</p>
              <ul>{(chosen.display?.reasons ?? chosen.reasons).map((x, n) => <li key={n}>{x}</li>)}</ul>
              {(chosen.display?.warnings ?? []).length > 0 && (
                <ul className="warnings">{chosen.display!.warnings.map((x, n) => <li key={n}>{x}</li>)}</ul>
              )}
              {sources(chosen).length > 0 && (
                <p className="reasons-sources">{t.sources}: {sources(chosen).map(([url, source]) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer">{source}</a>
                ))}</p>
              )}
            </div>
          ) : <p className="hint">{t.tapForReasons}</p>}
          <Visits t={t} view={view!} />
        </>
      )}
    </div>
  )
}

// Before a check: what Kaagaz does, in four steps.
function HowItWorks({ t }: { t: Strings }) {
  return (
    <section className="how">
      <ol>{t.howSteps.map((s, i) => <li key={i}><span className="how-num" aria-hidden="true">{i + 1}</span><span>{s}</span></li>)}</ol>
    </section>
  )
}

function Visits({ t, view }: { t: Strings; view: SessionView }) {
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
                <span className="visit-steps">{idx.length} {t.steps}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
