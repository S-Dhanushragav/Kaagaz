import { cropUrl, type Language, type SessionView } from '../api'
import type { Strings } from '../i18n'
import { docLabel } from '../labels'

// Each document's crop as soon as the finder hands it over; its label fills in once it has been read.
export default function Thumbnails({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const docs = view.documents ?? []
  if (!docs.length) return null
  const ids = docs.map((d) => d.id)
  const finding = !view.stages.find((s) => s.stage === 'find_documents')?.done
  return (
    <div className="thumbs-block">
      <p className="thumbs-title">{finding ? t.readingSoFar : t.documentsTitle} <span className="count">{docs.length}</span></p>
      <ul className="thumbs">
        {docs.map((d) => {
          // A clear close-up replaces the crop: a new version once it leaves the close-up list.
          const version = view.recapture?.documents.includes(d.id) ? 0 : 1
          return (
            <li key={d.id} className={d.read ? 'thumb' : 'thumb reading'}>
              <div className="thumb-image"><img src={cropUrl(view.id, d.id, version)} alt="" loading="lazy" /></div>
              <p className="thumb-label">{docLabel(view, d.id, ids, language, t)}</p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
