// Ask Kaagaz: the questions asked in the composer, each answered by the backend's fact-checked agent, with Listen, the
// sources of the rules it states and any "Add a photo" chips. Suggested questions come from the family's own problems
// (backend templates, no model).
import { useState } from 'react'
import { askAudioUrl, type AskChip, type AskReply } from '../api'
import { MUSE_SPARK_OPEN_NOTICE, type Strings } from '../i18n'
import { Camera, Link } from './Icons'
import ListenButton from './ListenButton'
import { Bot, Me } from './Chat'
import { CloseUp } from './Recapture'

export interface AskItem {
  key: number
  context: string // '' before a check; else the session or saved check it was about
  question: string
  reply: AskReply | null // null: still checking
  error: string | null
}

export function AskThread({ t, items, sessionId, sample, onReplanned, onAddPhotos }: {
  t: Strings; items: AskItem[]; sessionId: string | null; sample: boolean
  onReplanned: () => void; onAddPhotos: () => void
}) {
  return (
    <>
      {items.map((item) => (
        <div key={item.key} className="exchange ask">
          <Me>{item.question}</Me>
          <Bot wide={!!item.reply?.chips.length}>
            {item.error ? <p className="alert" role="alert">{item.error}</p>
              : item.reply ? <Answer t={t} reply={item.reply} sessionId={sessionId} sample={sample}
                onReplanned={onReplanned} onAddPhotos={onAddPhotos} />
                : <p className="status checking" aria-live="polite">{t.askChecking}</p>}
          </Bot>
        </div>
      ))}
    </>
  )
}

function Answer({ t, reply, sessionId, sample, onReplanned, onAddPhotos }: {
  t: Strings; reply: AskReply; sessionId: string | null; sample: boolean
  onReplanned: () => void; onAddPhotos: () => void
}) {
  const [open, setOpen] = useState<AskChip | null>(null)
  const pick = (chip: AskChip) => {
    if (chip.kind === 'closeup' && sessionId && chip.document_id) setOpen(open?.id === chip.id ? null : chip)
    else onAddPhotos()
  }
  return (
    <div className="ask-answer">
      <p className="ask-text">{reply.text}</p>
      {reply.note && <p className="ask-note">{reply.note}</p>}
      <div className="ask-meta">
        <ListenButton t={t} audioKey={`ask:${reply.id}`} url={askAudioUrl(reply.id)} />
        {reply.sources.length > 0 && (
          <span className="ask-sources">
            <span className="eyebrow">{t.sources}</span>
            {reply.sources.map((s) => (
              <a key={s.url} className="source-chip" href={s.url} target="_blank" rel="noreferrer"><Link />{s.label}</a>
            ))}
          </span>
        )}
      </div>
      {reply.chips.length > 0 && (
        <div className="ask-chips">
          {reply.chips.map((c) => (
            <button key={c.id} type="button" className={open?.id === c.id ? 'chip on' : 'chip'} aria-expanded={open?.id === c.id}
              onClick={() => pick(c)}><Camera size={18} /> {c.label}</button>
          ))}
        </div>
      )}
      {open && sessionId && open.document_id && (
        <CloseUp key={open.id} t={t} sessionId={sessionId} documentId={open.document_id} sample={sample}
          onReplanned={() => { setOpen(null); onReplanned() }} />
      )}
      <p className="powered-by" lang="en">{MUSE_SPARK_OPEN_NOTICE}</p>
    </div>
  )
}

export function Suggestions({ t, items, onPick }: { t: Strings; items: string[]; onPick: (q: string) => void }) {
  if (!items.length) return null
  return (
    <div className="suggestions">
      <p className="eyebrow">{t.askSuggestions}</p>
      <div className="suggestion-chips">
        {items.map((q) => <button key={q} type="button" className="chip suggestion" onClick={() => onPick(q)}>{q}</button>)}
      </div>
    </div>
  )
}
