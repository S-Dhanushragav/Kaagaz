import { useRef, useState } from 'react'
import { cropUrl, sendCloseup, type Language, type SessionView } from '../api'
import type { Strings } from '../i18n'
import { docLabel } from '../labels'
import { preparePhoto } from '../photos'
import { Camera } from './Icons'
import { Crop } from './Thumbnails'

// After reading: the documents that need a clearer photo (each with Take photo and Upload), items that looked like
// documents but could not be read, and, when nothing was read, the way to start again with photos or a recording.
// close_ups: the plan goes ahead and may change; hold: more than half are unclear, so the plan waits for photos.
export default function Recapture({ t, view, language, onReplanned, onAddPhotos, onRecordAgain }: {
  t: Strings; view: SessionView; language: Language; onReplanned?: () => void
  onAddPhotos: () => void; onRecordAgain: () => void
}) {
  const r = view.recapture
  const unidentified = r?.unidentified ?? []
  if (!r || (r.mode === 'none' && !unidentified.length)) return null
  if (r.mode === 'no_documents') {
    return (
      <div className="recapture">
        <p className="alert">{t.noDocuments}</p>
        <div className="button-row">
          <button type="button" className="button primary" onClick={onAddPhotos}><Camera />{t.addPhotos}</button>
          <button type="button" className="button" onClick={onRecordAgain}>{t.recordAgain}</button>
        </div>
      </div>
    )
  }
  const ready = view.status === 'done' && onReplanned
  const unclear = r.documents
  const read = r.read ?? unclear.length
  return (
    <div className="recapture">
      {r.mode === 'hold' && (
        <p className="alert">{t.holdLead.replace('{read}', String(read - unclear.length)).replace('{total}', String(read))
          .replace('{n}', String(unclear.length))}</p>
      )}
      {r.mode === 'close_ups' && <p className="recapture-lead">{t.recaptureCloseUps}</p>}
      {unclear.length > 0 && (
        <>
          <p className="thumbs-title">{t.needClearer} <span className="count">{unclear.length}</span></p>
          <ul className="closeups">
            {unclear.map((d) => (
              <li key={d}>
                <span className="closeup-thumb"><Crop src={cropUrl(view.id, d, 1)} /></span>
                <div className="closeup-body">
                  <strong>{docLabel(view, d, unclear, language, t)}</strong>
                  {ready && <CloseUp t={t} sessionId={view.id} documentId={d} sample={view.sample} onReplanned={onReplanned} />}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {unidentified.length > 0 && (
        <>
          <p className="note">{unidentified.length === 1 ? t.unidentifiedOne
            : t.unidentifiedMany.replace('{n}', String(unidentified.length))}</p>
          {ready && (
            <ul className="closeups">
              {unidentified.map((d) => (
                <li key={d}>
                  <span className="closeup-thumb"><Crop src={cropUrl(view.id, d, 1)} /></span>
                  <div className="closeup-body">
                    <CloseUp t={t} sessionId={view.id} documentId={d} sample={false} onReplanned={onReplanned} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

export function CloseUp({ t, sessionId, documentId, sample, onReplanned }: {
  t: Strings; sessionId: string; documentId: string; sample: boolean; onReplanned: () => void
}) {
  const camera = useRef<HTMLInputElement>(null)
  const gallery = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const send = async (photo: Blob | null) => {
    setBusy(true)
    setNote(null)
    try {
      // Resized and re-encoded in the browser: no EXIF (GPS location) leaves the phone.
      const reply = await sendCloseup(sessionId, documentId, photo ? await preparePhoto(photo) : null)
      if (reply.clear) { onReplanned(); return }
      setNote(t.stillUnclear)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
    setBusy(false)
  }
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) void send(f)
    e.target.value = ''
  }
  return (
    <div className="closeup">
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={pick} />
      <input ref={gallery} type="file" accept="image/*" hidden onChange={pick} />
      <div className="button-row">
        <button type="button" className="button" disabled={busy} onClick={() => camera.current?.click()}><Camera />{t.takePhoto}</button>
        <button type="button" className="button" disabled={busy} onClick={() => gallery.current?.click()}>{t.upload}</button>
        {sample && <button type="button" className="button" disabled={busy} onClick={() => void send(null)}>{t.useSampleCloseUp}</button>}
      </div>
      {busy && <p className="note" role="status">{t.readingPhoto}</p>}
      {note && <p className="note" role="status">{note}</p>}
    </div>
  )
}
