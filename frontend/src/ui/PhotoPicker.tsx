import { useEffect, useMemo, useRef, useState } from 'react'
import type { Strings } from '../i18n'
import { MAX_PHOTOS } from '../photos'
import { Camera } from './Icons'

// Photo mode: pick up to 12 photos. Without a `capture` attribute, phones offer the camera or the gallery (several
// photos at once); desktops show a file picker. The photos stay on the phone until "Check these photos", and are
// then resized and stripped of EXIF before upload (App -> photos.ts).
export default function PhotoPicker({ t, onDone, onCancel }: { t: Strings; onDone: (photos: File[]) => void; onCancel: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [tooMany, setTooMany] = useState(false)
  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files])
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls])

  const add = (list: FileList | null) => {
    const picked = Array.from(list ?? []).filter((f) => f.type.startsWith('image/'))
    const all = [...files, ...picked]
    setTooMany(all.length > MAX_PHOTOS)
    setFiles(all.slice(0, MAX_PHOTOS))
  }
  const remove = (i: number) => { setFiles(files.filter((_, j) => j !== i)); setTooMany(false) }

  return (
    <div className="photo-picker">
      <h3>{t.photosTitle}</h3>
      <ol className="guidance">{t.photosGuidance.map((g) => <li key={g}>{g}</li>)}</ol>
      <input ref={input} type="file" accept="image/*" multiple hidden
        onChange={(e) => { add(e.target.files); e.target.value = '' }} />
      {files.length > 0 && (
        <>
          <ul className="photo-grid">
            {urls.map((u, i) => (
              <li key={u}>
                <img src={u} alt="" />
                <button type="button" className="photo-remove" aria-label={t.removePhoto} onClick={() => remove(i)}>×</button>
              </li>
            ))}
          </ul>
          <p className="note">{t.photosChosen.replace('{n}', String(files.length))}</p>
        </>
      )}
      {tooMany && <p className="note" role="status">{t.tooManyPhotos}</p>}
      <div className="button-row">
        <button type="button" className={files.length ? 'button' : 'button primary'} disabled={files.length >= MAX_PHOTOS}
          onClick={() => input.current?.click()}><Camera />{files.length ? t.morePhotos : t.choosePhotos}</button>
        {files.length > 0 && <button type="button" className="button primary" onClick={() => onDone(files)}>{t.checkPhotos}</button>}
        <button type="button" className="button" onClick={onCancel}>{t.startOver}</button>
      </div>
    </div>
  )
}
