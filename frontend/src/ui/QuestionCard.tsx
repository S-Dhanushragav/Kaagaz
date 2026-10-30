import { useState } from 'react'
import { answerOption, audioUrl, type Question } from '../api'
import type { Strings } from '../i18n'
import { Mic } from './Icons'
import ListenButton from './ListenButton'
import type { Voice } from './voice'

// Big numbered buttons first, voice as a bonus.
export default function QuestionCard({ t, id, question, voice, onAnswered }: {
  t: Strings; id: string; question: Question; voice: Voice; onAnswered: (label: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const confirm = question.severity === 'confirm' || question.kind === 'compare'

  const choose = async (option: number) => {
    setBusy(true)
    try {
      await answerOption(id, question.question_id, option)
      onAnswered(question.shown[option])
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const disabled = busy || voice.busy
  return (
    <div className="question" aria-live="polite">
      <h3>{confirm ? t.confirmTitle : t.questionTitle}</h3>
      {question.member && <p className="question-member">{question.member}</p>}
      <div className="side-by-side">
        {question.values.map((v, i) => (
          <div key={i} className="spelling">
            <span className="spelling-doc">{t.docTypes[v.document_type] ?? v.document_type}</span>
            <strong>{v.value}</strong>
          </div>
        ))}
      </div>
      <ListenButton t={t} audioKey={`${id}:question:${question.question_id}`} url={audioUrl(id, 'question')} />
      <div className="options">
        {question.shown.map((label, i) => (
          <button key={i} type="button" className="option" disabled={disabled} onClick={() => void choose(i)}>
            <span className="option-num" aria-hidden="true">{i + 1}</span><span>{label}</span>
          </button>
        ))}
      </div>
      {voice.allowed && (
        <button type="button" className={voice.listening ? 'button mic listening' : 'button mic'}
          disabled={disabled && !voice.listening} onClick={voice.toggle}>
          <Mic />{voice.listening ? t.listening : t.mic}
        </button>
      )}
      {(voice.note || note) && <p className="note" role="status">{voice.note ?? note}</p>}
    </div>
  )
}
