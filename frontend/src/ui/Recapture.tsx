import { useRef, useState } from 'react'
import { sendCloseup, type Language, type SessionView } from '../api'
import type { Strings } from '../i18n'
import { docLabel } from '../labels'
import { Camera } from './Icons'

// What to record again: a close-up of a few documents, or (most unreadable / none found) the whole sweep.
export default function Recapture({ t, view, language, onReplanned }: {
  t: Strings; view: SessionView; language: Language; onReplanned?: () => void
}) {
  const r = view.recapture
  if (!r || r.mode === 'none') return null
  const ready = view.status === 'done' && onReplanned
  if (r.mode === 'no_documents') return <p className="alert">{t.noDocuments}</p>
  if (r.mode === 'sweep_again') return <p className="alert">{t.recaptureSweep}</p>
  return (
    <div className="recapture">
      <p className="recapture-lead">{t.recaptureCloseUps}</p>
      <ul className="closeups">
        {r.documents.map((d) => (
          <li key={d}>
            <strong>{docLabel(view, d, r.documents, language, t)}</strong>
            {ready && <CloseUp t={t} sessionId={view.id} documentId={d} sample={view.sample} onReplanned={onReplanned} />}
          </li>
        ))}
      </ul>
    </div>
  )
}

function CloseUp({ t, sessionId, documentId, sample, onReplanned }: {
  t: Strings; sessionId: string; documentId: string; sample: boolean; onReplanned: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const send = async (photo: Blob | null) => {
    setBusy(true)
    setNote(null)
    try {
      const reply = await sendCloseup(sessionId, documentId, photo)
      if (reply.clear) { onReplanned(); return }
      setNote(t.stillUnclear)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
    setBusy(false)
  }
  return (
    <div className="closeup">
      <input ref={input} type="file" accept="image/*" capture="environment" hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f); e.target.value = '' }} />
      <div className="button-row">
        <button type="button" className="button" disabled={busy} onClick={() => input.current?.click()}><Camera />{t.takePhoto}</button>
        {sample && <button type="button" className="button" disabled={busy} onClick={() => void send(null)}>{t.useSampleCloseUp}</button>}
      </div>
      {busy && <p className="note" role="status">{t.readingPhoto}</p>}
      {note && <p className="note" role="status">{note}</p>}
    </div>
  )
}
