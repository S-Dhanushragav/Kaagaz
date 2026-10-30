import type { ReactNode } from 'react'
import type { CatalogScheme, CheckFull, Language, SessionView } from '../api'
import { LANGUAGE_NAMES, type Strings } from '../i18n'
import Feedback from './Feedback'
import { formatDate } from '../casefile'
import { count } from '../counts'
import { RecheckComparison } from './PastCheck'
import { Camera, Logo } from './Icons'
import QuestionCard from './QuestionCard'
import Recapture from './Recapture'
import Recorder from './Recorder'
import SchemesCard from './SchemesCard'
import Thumbnails from './Thumbnails'
import { FamilyCard, PlanCard, ProblemsCard } from './Results'
import type { Voice } from './voice'

export type Check =
  | { kind: 'idle' }
  | { kind: 'recording' }
  | { kind: 'uploading'; sample: boolean; percent: number | null }
  | { kind: 'session'; sample: boolean; id: string; guestSecret: string }

export interface Answered { question: string; member: string | null; answer: string }

// `wide`: a card that fills the reading column (780 px); `full`: tables and cards that may use up to 960 px.
export function Bot({ children, wide, full }: { children: ReactNode; wide?: boolean; full?: boolean }) {
  return (
    <div className={['msg bot', wide || full ? 'wide' : '', full ? 'full' : ''].filter(Boolean).join(' ')}>
      <span className="avatar" aria-hidden="true"><Logo size={22} /></span>
      <div className="bubble">{children}</div>
    </div>
  )
}

export function Me({ children }: { children: ReactNode }) {
  return <div className="msg me"><div className="bubble">{children}</div></div>
}

export default function Chat({ t, language, schemes, check, view, error, answered, voice, onRecord, onSample, onRecorded,
  onCancelRecord, onAnswered, onReplanned, onNewCheck, latest, recheck, onOpenCheck, loggedIn, onSaveCheck, narrow,
  onOpenScheme }: {
  t: Strings; language: Language; schemes: CatalogScheme[]; check: Check; view: SessionView | null; error: string | null; answered: Answered[]
  voice: Voice; onRecord: () => void; onSample: () => void; onRecorded: (b: Blob) => void; onCancelRecord: () => void
  onAnswered: (label: string) => void; onReplanned: () => void; onNewCheck: () => void
  latest: CheckFull | null; recheck: boolean; onOpenCheck: (id: string, step: number | null) => void
  loggedIn: boolean; onSaveCheck: () => void; narrow: boolean; onOpenScheme: (id: string) => void
}) {
  const names = Object.fromEntries(schemes.map((s) => [s.id, s.name]))
  const started = check.kind !== 'idle'
  const sample = check.kind !== 'idle' && check.kind !== 'recording' && check.sample
  const stopped = view?.status === 'done' && (view.recapture?.mode === 'sweep_again' || view.recapture?.mode === 'no_documents')
  return (
    <>
      {/* A returning user's open steps come first; the steps of how Kaagaz works are then folded away. */}
      {latest && !started && <Bot><WelcomeBack t={t} language={language} latest={latest} onOpenCheck={onOpenCheck} /></Bot>}
      <Bot>
        <p className="lead">{t.welcome}</p>
        <p className="specimen-note">{t.specimen}</p>
        <HowItWorks t={t} folded={!!latest} />
      </Bot>
      <Bot>
        <p>{t.startPrompt}</p>
        {!started && (
          <div className="button-row start">
            <button type="button" className="button primary big" onClick={onRecord}><Camera />{t.record}</button>
            <button type="button" className="button big" onClick={onSample}>{t.trySample}</button>
          </div>
        )}
      </Bot>
      {started && <Me>{recheck ? `${t.checkAgain}: ${sample ? t.trySample : t.record}` : sample ? t.trySample : t.record}</Me>}

      {check.kind === 'recording' && <Bot wide><Recorder t={t} onDone={onRecorded} onCancel={onCancelRecord} /></Bot>}
      {check.kind === 'uploading' && <Bot><Uploading t={t} percent={check.percent} /></Bot>}
      {error && <Bot><p className="alert" role="alert">{t.error}: {error}</p></Bot>}

      {view && view.language !== language && (
        <p className="system-note">{t.sessionLanguage.replace('{lang}', LANGUAGE_NAMES[view.language])}</p>
      )}
      {view && <Bot><Progress t={t} language={language} view={view} /></Bot>}
      {view && (view.documents ?? []).length > 0 && <Bot wide><Thumbnails t={t} view={view} language={language} /></Bot>}
      {view && answered.map((a, i) => (
        <div key={i} className="exchange">
          <Bot><p className="asked">{t.questionTitle}{a.member ? `: ${a.member}` : ''}</p></Bot>
          <Me>{a.answer}</Me>
        </div>
      ))}
      {view?.status === 'waiting' && view.question && (
        <Bot wide>
          <QuestionCard key={view.question.question_id} t={t} id={view.id} question={view.question} voice={voice} onAnswered={onAnswered} />
        </Bot>
      )}
      {view?.status === 'error' && <Bot><p className="alert" role="alert">{t.error}: {view.error}</p></Bot>}
      {view && view.recapture && view.recapture.mode !== 'none' && (
        <Bot wide><Recapture t={t} view={view} language={language} onReplanned={stopped ? undefined : onReplanned} /></Bot>
      )}
      {stopped && <Bot><button type="button" className="button primary" onClick={onNewCheck}>{t.newCheck}</button></Bot>}
      {view?.status === 'done' && !stopped && (
        <>
          {view.recapture?.mode === 'close_ups' && <p className="system-note">{t.closeUpsNote}</p>}
          {view.check_id && <p className="system-note saved">✓ {t.savedNote}</p>}
          {view.check_id && view.recheck_of && (
            <Bot wide><RecheckComparison key={view.check_id} t={t} language={language} checkId={view.check_id} names={names} /></Bot>
          )}
          <Bot wide><PlanCard t={t} view={view}><Feedback key={view.id} t={t} sessionId={view.id} target="plan" /></PlanCard></Bot>
          <Bot full><SchemesCard key={view.id} t={t} view={view} language={language} schemes={schemes} narrow={narrow}
            onOpenScheme={onOpenScheme} /></Bot>
          <Bot wide><ProblemsCard t={t} view={view} language={language} /></Bot>
          <Bot wide><FamilyCard key={view.id} t={t} view={view} language={language} names={names} /></Bot>
          {!loggedIn && view.household && (
            <Bot>
              <div className="save-card">
                <p>{t.saveCheck}</p>
                <button type="button" className="button primary" onClick={onSaveCheck}>{t.saveCheckButton}</button>
              </div>
            </Bot>
          )}
        </>
      )}
    </>
  )
}

// What Kaagaz does, in four steps (the existing strings): open for a first visit, folded for a returning user.
function HowItWorks({ t, folded }: { t: Strings; folded: boolean }) {
  const steps = <ol className="how-steps">{t.howSteps.map((s, i) => <li key={i}>{s}</li>)}</ol>
  if (folded) {
    return (
      <details className="how">
        <summary>{t.howTitle}</summary>
        {steps}
      </details>
    )
  }
  return (
    <div className="how">
      <p className="how-title">{t.howTitle}</p>
      {steps}
    </div>
  )
}

// A returning user: what the last check found, and its open steps (tap one to open the check there).
function WelcomeBack({ t, language, latest, onOpenCheck }: {
  t: Strings; language: Language; latest: CheckFull; onOpenCheck: (id: string, step: number | null) => void
}) {
  const open = latest.data.steps.filter((s) => !latest.steps_done[String(s.index)])
  return (
    <div className="welcome-back">
      <p className="lead">{t.welcomeBack.replace('{date}', formatDate(latest.created, language))
        .replace('{problems}', count(language, 'problemFound', latest.problems))
        .replace('{visits}', count(language, 'visitOpen', latest.open_visits))}</p>
      {open.length > 0 && (
        <>
          <p className="eyebrow">{t.stillToDo}</p>
          <ul className="open-steps">
            {open.slice(0, 5).map((s) => (
              <li key={s.index}>
                <button type="button" className="open-step" onClick={() => onOpenCheck(latest.id, s.index)}>
                  <span className="open-step-box" aria-hidden="true" />
                  <span>{s.office ? <strong>{s.office.text}: </strong> : null}{s.voice}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function Uploading({ t, percent }: { t: Strings; percent: number | null }) {
  if (percent === null) return <p className="status" aria-live="polite">{t.working}…</p>
  const sent = percent >= 100
  return (
    <div className="upload">
      <p className="status" aria-live="polite">{sent ? t.uploaded : `${t.uploading} ${percent}%`}</p>
      <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={t.uploading}>
        <div className="fill" style={{ width: percent + '%' }} />
      </div>
    </div>
  )
}

function Progress({ t, language, view }: { t: Strings; language: Language; view: SessionView }) {
  const finished = view.stages.every((s) => s.done)
  if (finished) {
    const total = view.stages.reduce((sum, s) => sum + (s.seconds ?? 0), 0)
    return (
      <>
        <p className="progress-done"><span className="tick" aria-hidden="true">✓</span>{t.checkedIn.replace('{time}', count(language, 'secondsTaken', Math.round(total)))}</p>
        <p className="powered-by">{t.poweredBy}</p>
      </>
    )
  }
  return (
    <div aria-live="polite">
      <p className="status">{t.working}</p>
      <ol className="stages">
        {view.stages.map((s) => {
          const state = s.done ? 'done' : view.stage === s.stage ? 'active' : 'todo'
          return (
            <li key={s.stage} className={state}>
              <span className="stage-mark" aria-hidden="true">{s.done ? '✓' : ''}</span>
              <span>{t.stages[s.stage]}</span>
              {s.done && s.seconds !== null && <span className="secs">{s.seconds.toFixed(0)} s</span>}
            </li>
          )
        })}
      </ol>
      <p className="powered-by">{t.poweredBy}</p>
    </div>
  )
}
