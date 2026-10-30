import { useState, type ReactNode } from 'react'
import { audioUrl, type Language, type PlannerIssue, type SessionView, type Shown, type Step, type StepDisplay } from '../api'
import { playAll, stop, useAudio } from '../audio'
import type { Strings } from '../i18n'
import { docLabel, memberName, OUTCOME_MARK, sources } from '../labels'
import { Download, IssueIcon, Office, Play, Stop } from './Icons'
import ListenButton from './ListenButton'

function Fact({ t, shown }: { t: Strings; shown: Shown }) {
  return <>{shown.text}{!shown.verified && <span className="unverified"> ({t.unverified})</span>}</>
}

const stepKey = (id: string, i: number) => `${id}:step-${i}`

// ---------- What to do: steps grouped by office visit ----------

export function PlanCard({ t, view, children }: { t: Strings; view: SessionView; children?: ReactNode }) {
  const { key, group } = useAudio()
  const id = view.id
  const steps = view.plan?.steps ?? []
  const display = (i: number): StepDisplay | null => view.speech?.[i]?.display ?? null
  const visits = new Map<number, number[]>()
  steps.forEach((s, i) => { if (s.kind === 'fix' && s.visit) visits.set(s.visit, [...(visits.get(s.visit) ?? []), i]) })
  const groups = [...visits.entries()].sort(([a], [b]) => a - b)
  const office = steps.map((s, i) => [s, i] as const).filter(([s]) => s.kind === 'ask_at_office').map(([, i]) => i)
  const asked = steps.filter((s) => s.kind === 'question')
  const order = [...groups.flatMap(([, idx]) => idx), ...office]
  const playingAll = group === `plan:${id}`
  let n = 0

  return (
    <section className="card-block plan-card" aria-labelledby="plan-title">
      <header className="card-head">
        <h2 id="plan-title">{t.planTitle}</h2>
        {order.length > 0 && (
          <button type="button" className={playingAll ? 'listen-all playing' : 'listen-all'} aria-pressed={playingAll}
            onClick={() => (playingAll ? stop() : playAll(`plan:${id}`, order.map((i) => [stepKey(id, i), audioUrl(id, `step-${i}`)])))}>
            {playingAll ? <Stop /> : <Play />}<span>{playingAll ? t.stop : t.listenAll}</span>
          </button>
        )}
      </header>
      {!order.length && <p>{t.noPlan}</p>}
      {groups.map(([visit, idx]) => {
        const where = display(idx[0])?.office
        return (
          <div key={visit} className="visit-group">
            <h3 className="visit-title">
              <span className="visit-num" aria-hidden="true">{visit}</span>
              <span>{t.visit} {visit}{where && <>: <Office size={18} /> <Fact t={t} shown={where} /></>}</span>
            </h3>
            <ol className="step-list">
              {idx.map((i) => <FixStep key={i} t={t} id={id} step={steps[i]} index={i} number={++n} display={display(i)}
                current={key === stepKey(id, i)} />)}
            </ol>
          </div>
        )
      })}
      {office.length > 0 && (
        <div className="visit-group">
          <h3 className="visit-title"><span className="visit-num ask" aria-hidden="true">?</span><span>{t.askAtOffice}</span></h3>
          <ol className="step-list">
            {office.map((i) => <FixStep key={i} t={t} id={id} step={steps[i]} index={i} number={++n} display={null}
              current={key === stepKey(id, i)} />)}
          </ol>
        </div>
      )}
      {asked.length > 0 && (
        <details className="asked-list">
          <summary>{t.questionsAsked}</summary>
          {asked.map((s, i) => <p key={i}>{s.question} → <strong>{s.answer}</strong></p>)}
        </details>
      )}
      {children}
    </section>
  )
}

function FixStep({ t, id, step, index, number, display, current }: {
  t: Strings; id: string; step: Step; index: number; number: number; display: StepDisplay | null; current: boolean
}) {
  const download = () => {
    const url = URL.createObjectURL(new Blob([step.declaration ?? ''], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'declaration-draft.txt'
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <li className={current ? 'step current' : 'step'} aria-current={current ? 'step' : undefined}>
      <span className="step-num" aria-hidden="true">{number}</span>
      <div className="step-body">
        <p className="step-voice">{step.voice}</p>
        {display && (display.bring.length > 0 || display.fee || display.time_limit) && (
          <dl className="step-facts">
            {display.bring.length > 0 && <div><dt>{t.bring}</dt><dd><ul>{display.bring.map((b) => <li key={b.text}><Fact t={t} shown={b} /></li>)}</ul></dd></div>}
            {display.fee && <div><dt>{t.fee}</dt><dd><Fact t={t} shown={display.fee} /></dd></div>}
            {display.time_limit && <div><dt>{t.timeLimit}</dt><dd><Fact t={t} shown={display.time_limit} /></dd></div>}
          </dl>
        )}
        <div className="step-actions">
          <ListenButton t={t} audioKey={stepKey(id, index)} url={audioUrl(id, `step-${index}`)} label={String(number)} />
          {step.declaration && <button type="button" className="button slim" onClick={download}><Download />{t.downloadDeclaration}</button>}
        </div>
      </div>
    </li>
  )
}

// ---------- Problems found: one line each, with the person and the document ----------

interface Problem { key: string; type: string; who: string | null; docs: string; waiting: boolean; blocker: boolean }

export function ProblemsCard({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const hh = view.household
  if (!hh) return null
  const who = (i: PlannerIssue) => {
    const m = hh.members.find((x) => x.member_id === i.member_id)
    return m ? memberName(m, language, t) : (language === 'en' ? i.member_name : i.member_name_mr ?? i.member_name)
  }
  const label = (ids: string[]) => ids.map((d) => docLabel(view, d, ids, language, t).replace(/:.*$/, '')).join(', ')
  const missing = (i: PlannerIssue) => (i.document_type && t.docTypes[i.document_type]) || ''
  const unreadable = hh.issues.filter((i) => i.type === 'unreadable' && i.severity !== 'info').flatMap((i) => i.documents)
  const problems: Problem[] = [
    ...(view.issues ?? []).map((i) => ({ key: i.id, type: i.type, who: who(i), docs: i.type === 'missing_document' ? missing(i) : label(Object.keys(i.documents)),
      waiting: false, blocker: i.severity === 'blocker' })),
    ...(view.waiting ?? []).map((i) => ({ key: `w-${i.id}`, type: i.type, who: who(i as PlannerIssue), docs: label(Object.keys(i.documents)),
      waiting: true, blocker: false })),
    ...unreadable.map((d) => ({ key: `u-${d}`, type: 'unreadable', who: null, docs: docLabel(view, d, unreadable, language, t),
      waiting: false, blocker: true })),
  ]
  return (
    <section className="card-block" aria-labelledby="problems-title">
      <header className="card-head"><h2 id="problems-title">{t.issuesTitle}</h2>
        {problems.length > 0 && <span className="count">{problems.length}</span>}</header>
      {problems.length === 0 ? <p className="all-clear">✓ {t.noIssues}</p> : (
        <ul className="problems">
          {problems.map((p) => (
            <li key={p.key} className={p.waiting ? 'problem waiting' : p.blocker ? 'problem blocker' : 'problem'}>
              <span className="problem-icon"><IssueIcon type={p.waiting ? 'waiting' : p.type} /></span>
              <span className="problem-text">
                <strong>{t.issueTypes[p.type] ?? p.type}</strong>
                {(p.who || p.docs) && <span className="problem-detail">{[p.who, p.docs].filter(Boolean).join(' · ')}</span>}
                {p.waiting && <span className="tag waiting-tag">{t.waitingTitle}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------- Your family: one collapsible row per member ----------

export function FamilyCard({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const hh = view.household
  const results = view.results ?? []
  const withProblems = (memberId: string) =>
    (view.issues ?? []).some((i) => i.member_id === memberId) || (view.waiting ?? []).some((i) => i.member_id === memberId)
    || results.some((r) => r.member_id === memberId && r.outcome === 'blocked_by_issues')
  const first = hh?.members.find((m) => withProblems(m.member_id))?.member_id ?? null
  const [open, setOpen] = useState<Record<string, boolean>>(() => (first ? { [first]: true } : {}))
  if (!hh) return null
  return (
    <section className="card-block" aria-labelledby="family-title">
      <header className="card-head"><h2 id="family-title">{t.householdTitle}</h2></header>
      <div className="members">
        {hh.members.map((m) => {
          const rs = results.filter((r) => r.member_id === m.member_id)
          return (
            <details key={m.member_id} className="member" open={!!open[m.member_id]}
              onToggle={(e) => { const o = (e.target as HTMLDetailsElement).open; setOpen((s) => (s[m.member_id] === o ? s : { ...s, [m.member_id]: o })) }}>
              <summary>
                <span className="member-name">{memberName(m, language, t)}
                  {!m.on_ration_card && <span className="tag">{t.notOnCard}</span>}</span>
                <span className="member-marks" aria-hidden="true">
                  {rs.map((r) => <span key={r.scheme_id} className={`cell mini ${r.outcome}`}>{OUTCOME_MARK[r.outcome]}</span>)}
                </span>
              </summary>
              <p className="member-docs">{Object.keys(m.documents).map((d) => t.docTypes[d] ?? d).join(', ')}</p>
              <ul className="member-schemes">
                {rs.map((r) => (
                  <li key={r.scheme_id} className={`member-scheme ${r.outcome}`}>
                    <p className="member-scheme-head">
                      <span className={`cell mini ${r.outcome}`} aria-hidden="true">{OUTCOME_MARK[r.outcome]}</span>
                      <strong>{r.scheme_name}</strong><span className="outcome-text">{t.outcomes[r.outcome]}</span>
                    </p>
                    <ul className="why">{(r.display?.reasons ?? r.reasons).map((x, n) => <li key={n}>{x}</li>)}</ul>
                    {(r.display?.warnings ?? []).length > 0 && (
                      <ul className="why warnings">{r.display!.warnings.map((x, n) => <li key={n}>{x}</li>)}</ul>
                    )}
                    {sources(r).length > 0 && (
                      <p className="why-sources">{t.sources}: {sources(r).map(([url, source]) => (
                        <a key={url} href={url} target="_blank" rel="noreferrer">{source}</a>
                      ))}</p>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )
        })}
      </div>
    </section>
  )
}
