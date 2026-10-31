import { useState } from 'react'
import { cropUrl, type Language, type SessionView } from '../api'
import type { Strings } from '../i18n'
import { docLabel } from '../labels'
import { DocIcon } from './Icons'

// Each document's crop as soon as the finder hands it over; its label fills in once it has been read. Once reading
// is done and some documents need a clearer photo, this lists only the documents read clearly (the others are listed,
// with their photo buttons, under "Need a clearer photo").
export default function Thumbnails({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const all = view.documents ?? []
  const r = view.recapture
  const sorted = r && r.mode !== 'no_documents' && (r.documents.length > 0 || (r.unidentified ?? []).length > 0)
  const docs = sorted ? all.filter((d) => !r.documents.includes(d.id) && !(r.unidentified ?? []).includes(d.id)) : all
  if (!docs.length) return null
  const ids = all.map((d) => d.id)
  const finding = !view.stages.find((s) => s.stage === 'find_documents')?.done
  const title = finding ? t.readingSoFar : sorted ? t.readClearly : t.documentsTitle
  return (
    <div className="thumbs-block">
      <p className="thumbs-title">{title} <span className="count">{docs.length}</span></p>
      <ul className="thumbs">
        {docs.map((d) => {
          // Until a document is read the server sends only a coarse preview; a clear close-up replaces the crop.
          const version = (d.read ? 1 : 0) + (view.recapture?.documents.includes(d.id) ? 0 : 2)
          return (
            <li key={d.id} className={d.read ? 'thumb' : 'thumb reading'}>
              <div className="thumb-image"><Crop key={version} src={cropUrl(view.id, d.id, version)} /></div>
              <p className="thumb-label">{docLabel(view, d.id, ids, language, t)}</p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// The crop, or a document icon when the server will not show it (an identity number it could not locate).
export function Crop({ src }: { src: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <span className="thumb-icon"><DocIcon /></span>
  return <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />
}
