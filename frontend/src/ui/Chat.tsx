import type { ReactNode } from 'react'
import type { Language, SessionView } from '../api'
import { LANGUAGE_NAMES, type Strings } from '../i18n'
import { Camera, Logo } from './Icons'
import QuestionCard from './QuestionCard'
import Recapture from './Recapture'
import Recorder from './Recorder'
import { Plan, Results } from './Results'
import type { Voice } from './voice'

export type Check =
  | { kind: 'idle' }
  | { kind: 'recording' }
  | { kind: 'uploading'; sample: boolean; percent: number | null }
  | { kind: 'session'; sample: boolean; id: string }

export interface Answered { question: string; member: string | null; answer: string }

export function Bot({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'msg bot wide' : 'msg bot'}>
      <span className="avatar" aria-hidden="true"><Logo size={22} /></span>
      <div className="bubble">{children}</div>
    </div>
  )
}

export function Me({ children }: { children: ReactNode }) {
  return <div className="msg me"><div className="bubble">{children}</div></div>
}

export default function Chat({ t, language, check, view, error, answered, voice, onRecord, onSample, onRecorded,
  onCancelRecord, onAnswered, onReplanned, onNewCheck }: {
  t: Strings; language: Language; check: Check; view: SessionView | null; error: string | null; answered: Answered[]
  voice: Voice; onRecord: () => void; onSample: () => void; onRecorded: (b: Blob) => void; onCancelRecord: () => void
  onAnswered: (label: string) => void; onReplanned: () => void; onNewCheck: () => void
}) {
  const started = check.kind !== 'idle'
  const sample = check.kind !== 'idle' && check.kind !== 'recording' && check.sample
  const stopped = view?.status === 'done' && (view.recapture?.mode === 'sweep_again' || view.recapture?.mode === 'no_documents')
  return (
    <>
      <Bot>
        <p className="lead">{t.welcome}</p>
        <p className="specimen-note">{t.specimen}</p>
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
      {started && <Me>{sample ? t.trySample : t.record}</Me>}

      {check.kind === 'recording' && <Bot wide><Recorder t={t} onDone={onRecorded} onCancel={onCancelRecord} /></Bot>}
      {check.kind === 'uploading' && <Bot><Uploading t={t} percent={check.percent} /></Bot>}
      {error && <Bot><p className="alert" role="alert">{t.error}: {error}</p></Bot>}

      {view && view.language !== language && (
        <p className="system-note">{t.sessionLanguage.replace('{lang}', LANGUAGE_NAMES[view.language])}</p>
      )}
      {view && <Bot><Progress t={t} view={view} /></Bot>}
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
          <Bot wide><Plan t={t} id={view.id} view={view} /></Bot>
          {view.household && <Bot wide><Results t={t} view={view} language={language} /></Bot>}
        </>
      )}
    </>
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

function Progress({ t, view }: { t: Strings; view: SessionView }) {
  const finished = view.stages.every((s) => s.done)
  if (finished) {
    const total = view.stages.reduce((sum, s) => sum + (s.seconds ?? 0), 0)
    return <p className="progress-done"><span className="tick" aria-hidden="true">✓</span>{t.checkedIn.replace('{s}', total.toFixed(0))}</p>
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
    </div>
  )
}
