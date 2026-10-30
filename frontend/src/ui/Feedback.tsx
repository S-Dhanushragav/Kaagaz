import { useState } from 'react'
import { sendFeedback } from '../api'
import type { Strings } from '../i18n'
import { ThumbDown, ThumbUp } from './Icons'

// Thumbs up/down on the plan or an answer; a thumbs down asks what was wrong (optional).
export default function Feedback({ t, sessionId, target }: { t: Strings; sessionId: string; target: string }) {
  const [value, setValue] = useState<'up' | 'down' | null>(null)
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState(false)
  const send = (v: 'up' | 'down', text?: string) => {
    setSent(true)
    void sendFeedback(sessionId, target, v, text).catch(() => { /* feedback is best effort */ })
  }
  const choose = (v: 'up' | 'down') => {
    setValue(v)
    if (v === 'up') send(v)
  }
  if (sent) return <p className="feedback-thanks" role="status">{t.feedbackThanks}</p>
  return (
    <div className="feedback">
      <span className="feedback-ask">{t.feedbackAsk}</span>
      <div className="feedback-buttons">
        <button type="button" className={value === 'up' ? 'thumb-button on' : 'thumb-button'} aria-pressed={value === 'up'}
          aria-label={t.helpful} onClick={() => choose('up')}><ThumbUp /></button>
        <button type="button" className={value === 'down' ? 'thumb-button on' : 'thumb-button'} aria-pressed={value === 'down'}
          aria-label={t.notHelpful} onClick={() => choose('down')}><ThumbDown /></button>
      </div>
      {value === 'down' && (
        <form className="feedback-form" onSubmit={(e) => { e.preventDefault(); send('down', comment.trim()) }}>
          <label className="sr-only" htmlFor={`fb-${target}`}>{t.feedbackComment}</label>
          <textarea id={`fb-${target}`} rows={2} maxLength={500} placeholder={t.feedbackComment} value={comment}
            onChange={(e) => setComment(e.target.value)} />
          <button type="submit" className="button slim primary">{t.send}</button>
        </form>
      )}
    </div>
  )
}
