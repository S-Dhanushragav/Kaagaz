import { useEffect, useState } from 'react'
import { myCheck, storedAudioUrl, type CatalogScheme, type CheckFull, type Comparison, type Language, type StoredProblem } from '../api'
import { changeLine, checkAsView, formatDate, problemLine } from '../casefile'
import type { Strings } from '../i18n'
import { OUTCOME_MARK } from '../labels'
import { Camera, IssueIcon } from './Icons'
import { FamilyCard, PlanCard } from './Results'
import SchemesCard from './SchemesCard'

export function ProblemList({ t, language, problems }: { t: Strings; language: Language; problems: StoredProblem[] }) {
  return (
    <ul className="problems">
      {problems.map((p, i) => {
        const line = problemLine(t, language, p)
        return (
          <li key={i} className={p.waiting ? 'problem waiting' : 'problem'}>
            <span className="problem-icon"><IssueIcon type={p.waiting ? 'waiting' : p.type} /></span>
            <span className="problem-text">
              <strong>{line.title}</strong>
              {line.detail && <span className="problem-detail">{line.detail}</span>}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export function ComparisonCard({ t, language, comparison, names }: {
  t: Strings; language: Language; comparison: Comparison; names: Record<string, string>
}) {
  const c = comparison
  const nothing = !c.fixed.length && !c.new.length && !c.outcomes_changed.length
  const section = (title: string, kind: string, problems: StoredProblem[]) => problems.length > 0 && (
    <div className={`compare-group ${kind}`}>
      <h3>{title} <span className="count">{problems.length}</span></h3>
      <ProblemList t={t} language={language} problems={problems} />
    </div>
  )
  return (
    <section className="card-block compare" aria-labelledby="compare-title">
      <header className="card-head"><h2 id="compare-title">{t.compareTitle.replace('{date}', formatDate(c.previous_created, language))}</h2></header>
      {nothing && <p>{t.noChanges}</p>}
      {section(t.fixed, 'fixed', c.fixed)}
      {section(t.newProblems, 'new', c.new)}
      {section(t.stillOpen, 'open', c.still_open)}
      {c.outcomes_changed.length > 0 && (
        <div className="compare-group changes">
          <h3>{t.schemeChanges}</h3>
          <ul className="changes-list">
            {c.outcomes_changed.map((o, i) => {
              const line = changeLine(t, language, o, names)
              return (
                <li key={i}>
                  <span className={`cell mini ${o.after}`} aria-hidden="true">{OUTCOME_MARK[o.after]}</span>
                  <span><strong>{line.title}</strong>{line.detail && <span className="problem-detail"> · {line.detail}</span>}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}

// After "Check again": once the new check is saved, what changed since the one it re-checks.
export function RecheckComparison({ t, language, checkId, names }: {
  t: Strings; language: Language; checkId: string; names: Record<string, string>
}) {
  const [comparison, setComparison] = useState<Comparison | null>(null)
  useEffect(() => {
    let live = true
    myCheck(checkId).then((c) => { if (live) setComparison(c.comparison) }).catch(() => { /* shown without it */ })
    return () => { live = false }
  }, [checkId])
  return comparison ? <ComparisonCard t={t} language={language} comparison={comparison} names={names} /> : null
}

// A saved check, read-only, with a checkbox per plan step and "Check again".
export default function PastCheck({ t, language, check, schemes, focus, onTick, onCheckAgain, narrow, onOpenScheme }: {
  t: Strings; language: Language; check: CheckFull; schemes: CatalogScheme[]; focus: number | null
  onTick: (step: number, done: boolean) => void; onCheckAgain: (sample: boolean) => void
  narrow: boolean; onOpenScheme: (id: string) => void
}) {
  const view = checkAsView(check)
  const names = Object.fromEntries(schemes.map((s) => [s.id, s.name]))
  useEffect(() => {
    if (focus !== null) document.getElementById(`step-${focus}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus, check.id])
  return (
    <div className="past">
      <header className="past-head">
        <p className="eyebrow">{t.yourChecks}</p>
        <h1>{t.checkOf.replace('{date}', formatDate(check.created, language))}</h1>
        <p>{t.pastNote}</p>
      </header>
      {check.comparison && <ComparisonCard t={t} language={language} comparison={check.comparison} names={names} />}
      <PlanCard t={t} view={view} audioFor={(i) => storedAudioUrl(check.id, i)}
        ticks={{ done: check.steps_done, onToggle: onTick, focus }} />
      <div className="past-wide">
        <SchemesCard key={check.id} t={t} view={view} language={language} schemes={schemes} narrow={narrow}
          onOpenScheme={onOpenScheme} />
      </div>
      <section className="card-block" aria-labelledby="past-problems">
        <header className="card-head"><h2 id="past-problems">{t.issuesTitle}</h2>
          {check.data.problems.length > 0 && <span className="count">{check.data.problems.length}</span>}</header>
        {check.data.problems.length ? <ProblemList t={t} language={language} problems={check.data.problems} />
          : <p className="all-clear">✓ {t.noIssues}</p>}
      </section>
      <FamilyCard key={check.id} t={t} view={view} language={language} names={names} />
      <section className="card-block again" aria-labelledby="again-title">
        <header className="card-head"><h2 id="again-title">{t.checkAgain}</h2></header>
        <p>{t.checkAgainLead}</p>
        <div className="button-row">
          <button type="button" className="button primary big" onClick={() => onCheckAgain(false)}><Camera />{t.recordAgain}</button>
          <button type="button" className="button big" onClick={() => onCheckAgain(true)}>{t.sampleAgain}</button>
        </div>
      </section>
    </div>
  )
}
