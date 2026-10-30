import { audioUrl, type Language, type SessionView, type Shown, type Step, type StepDisplay } from '../api'
import type { Strings } from '../i18n'
import { docLabel, memberName, sources } from '../labels'
import ListenButton from './ListenButton'

// ---------- the plan ----------

function Fact({ t, shown }: { t: Strings; shown: Shown }) {
  return <>{shown.text}{!shown.verified && <span className="unverified"> ({t.unverified})</span>}</>
}

export function Plan({ t, id, view }: { t: Strings; id: string; view: SessionView }) {
  const steps = view.plan?.steps ?? []
  const display = (i: number): StepDisplay | null => view.speech?.[i]?.display ?? null
  if (!steps.length) return <section className="plan"><h2>{t.planTitle}</h2><p>{t.noPlan}</p></section>
  const visits = new Map<number, number[]>()
  steps.forEach((s, i) => { if (s.kind === 'fix' && s.visit) visits.set(s.visit, [...(visits.get(s.visit) ?? []), i]) })
  const asked = steps.map((s, i) => [s, i] as const).filter(([s]) => s.kind === 'question')
  const office = steps.map((s, i) => [s, i] as const).filter(([s]) => s.kind === 'ask_at_office')
  return (
    <section className="plan">
      <h2>{t.planTitle}</h2>
      {[...visits.entries()].sort(([a], [b]) => a - b).map(([visit, idx]) => (
        <div key={visit} className="visit">
          <h3>{t.visit} {visit}{display(idx[0])?.office && <>: <Fact t={t} shown={display(idx[0])!.office!} /></>}</h3>
          {idx.map((i) => <FixStep key={i} t={t} id={id} step={steps[i]} index={i} display={display(i)} />)}
        </div>
      ))}
      {office.length > 0 && (
        <div className="visit">
          <h3>{t.askAtOffice}</h3>
          {office.map(([s, i]) => <FixStep key={i} t={t} id={id} step={s} index={i} display={null} />)}
        </div>
      )}
      {asked.length > 0 && (
        <details>
          <summary>{t.questionsAsked}</summary>
          {asked.map(([s, i]) => <p key={i}>{s.question} → <strong>{s.answer}</strong></p>)}
        </details>
      )}
    </section>
  )
}

function FixStep({ t, id, step, index, display }: { t: Strings; id: string; step: Step; index: number; display: StepDisplay | null }) {
  const download = () => {
    const url = URL.createObjectURL(new Blob([step.declaration ?? ''], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'declaration-draft.txt'
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="step">
      <p className="voice">{step.voice}</p>
      <ListenButton t={t} audioKey={`${id}:step-${index}`} url={audioUrl(id, `step-${index}`)} />
      {display && (display.bring.length > 0 || display.fee || display.time_limit) && (
        <dl>
          {display.bring.map((b) => <div key={b.text}><dt>{t.bring}</dt><dd><Fact t={t} shown={b} /></dd></div>)}
          {display.fee && <div><dt>{t.fee}</dt><dd><Fact t={t} shown={display.fee} /></dd></div>}
          {display.time_limit && <div><dt>{t.timeLimit}</dt><dd><Fact t={t} shown={display.time_limit} /></dd></div>}
        </dl>
      )}
      {step.declaration && <button type="button" className="button" onClick={download}>⬇ {t.downloadDeclaration}</button>}
    </div>
  )
}

export function Results({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const hh = view.household!
  const byMember = new Map<string, NonNullable<SessionView['results']>>()
  for (const r of view.results ?? []) byMember.set(r.member_id, [...(byMember.get(r.member_id) ?? []), r])
  const problems = hh.issues.filter((i) => i.severity !== 'info')
  const unreadable = problems.filter((i) => i.type === 'unreadable').flatMap((i) => i.documents)
  return (
    <>
      <section className="result-block">
        <h2>{t.documentsTitle}</h2>
        <ul className="docs">
          {Object.values(hh.documents).map((d) => (
            <li key={d.document_id}>{t.docTypes[d.doc_type ?? ''] ?? d.doc_type ?? '?'}{d.unreadable ? ` (${t.issueTypes.unreadable})` : ''}</li>
          ))}
        </ul>
      </section>
      <section className="result-block">
        <h2>{t.issuesTitle}</h2>
        {problems.length === 0 ? <p>{t.noIssues}</p> : (
          <ul className="issues">
            {problems.map((i, n) => {
              const m = hh.members.find((x) => x.member_id === i.member_id)
              // 'Could not read' names the document; other problems name the person.
              const what = i.type === 'unreadable' && i.documents.length
                ? docLabel(view, i.documents[0], unreadable, language, t)
                : m ? memberName(m, language, t) : ''
              return <li key={n} className={i.severity}>{t.issueTypes[i.type] ?? i.type}{what ? `: ${what}` : ''}</li>
            })}
          </ul>
        )}
      </section>
      <section className="result-block">
        <h2>{t.householdTitle}</h2>
        {hh.members.map((m) => (
          <div key={m.member_id} className="member-card">
            <h3>{memberName(m, language, t)}{!m.on_ration_card && <span className="tag"> {t.notOnCard}</span>}</h3>
            <p className="small">{Object.keys(m.documents).map((d) => t.docTypes[d] ?? d).join(', ')}</p>
            <ul className="schemes">
              {(byMember.get(m.member_id) ?? []).map((r) => (
                <li key={r.scheme_id} className={`outcome ${r.outcome}`}>
                  <details>
                    <summary><strong>{r.scheme_name}</strong>: {t.outcomes[r.outcome]}</summary>
                    <ul className="small">{(r.display?.reasons ?? r.reasons).map((x, n) => <li key={n}>{x}</li>)}</ul>
                    {(r.display?.warnings ?? []).length > 0 && (
                      <ul className="small warnings">{r.display!.warnings.map((x, n) => <li key={n}>{x}</li>)}</ul>
                    )}
                    <p className="small">{t.sources}: {sources(r).map(([url, source]) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">{source}</a>
                    ))}</p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </>
  )
}
