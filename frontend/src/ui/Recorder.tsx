import { useEffect, useRef, useState } from 'react'
import type { Strings } from '../i18n'

const MAX_RECORD_S = 45
// 1080p at 8 Mbps: ~20 MB for a 20 s sweep, ~45 MB at most (server limit 60 MB). At 720p the ration card often
// could not be read (HH001 test: 3 false 'add to ration card' steps; at 1080p none).
const VIDEO_BITS_PER_SECOND = 8_000_000

function pickVideoType(): string | undefined {
  return ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4']
    .find((type) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type))
}

export default function Recorder({ t, onDone, onCancel }: { t: Strings; onDone: (b: Blob) => void; onCancel: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const [recording, setRecording] = useState(false)
  const [left, setLeft] = useState(MAX_RECORD_S)
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState(false) // camera stream live: before that, Start would do nothing

  useEffect(() => {
    let cancelled = false
    navigator.mediaDevices?.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
    }).then((stream) => {
      if (cancelled) { stream.getTracks().forEach((tr) => tr.stop()); return }
      streamRef.current = stream
      if (videoRef.current) videoRef.current.srcObject = stream
      setReady(true)
    }).catch(() => setFailed(true))
    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach((tr) => tr.stop())
    }
  }, [])

  useEffect(() => {
    if (!recording) return
    const timer = setInterval(() => setLeft((s) => {
      if (s <= 1) { recorderRef.current?.stop(); return 0 }
      return s - 1
    }), 1000)
    return () => clearInterval(timer)
  }, [recording])

  const start = () => {
    const stream = streamRef.current
    if (!stream) return
    const type = pickVideoType()
    const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: VIDEO_BITS_PER_SECOND })
    const chunks: Blob[] = []
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
    recorder.onstop = () => {
      setRecording(false)
      streamRef.current?.getTracks().forEach((tr) => tr.stop())
      onDone(new Blob(chunks, { type: recorder.mimeType || type || 'video/webm' }))
    }
    recorderRef.current = recorder
    setLeft(MAX_RECORD_S)
    recorder.start(1000)
    setRecording(true)
  }

  if (failed) {
    return (
      <div className="recorder">
        <p className="alert">{t.cameraError}</p>
        <button type="button" className="button" onClick={onCancel}>{t.startOver}</button>
      </div>
    )
  }
  return (
    <div className="recorder">
      {!recording && (
        <>
          <h3>{t.guidanceTitle}</h3>
          <ol className="guidance">{t.guidance.map((g) => <li key={g}>{g}</li>)}</ol>
        </>
      )}
      <div className="preview-frame">
        <video ref={videoRef} className="preview" autoPlay playsInline muted />
        {recording && <span className="rec-badge" aria-live="polite">● {left} {t.secondsLeft}</span>}
      </div>
      {recording ? (
        <button type="button" className="button primary danger" onClick={() => recorderRef.current?.stop()}>■ {t.stopRecording}</button>
      ) : (
        <div className="button-row">
          <button type="button" className="button primary" disabled={!ready} onClick={start}>● {t.startRecording}</button>
          <button type="button" className="button" onClick={onCancel}>{t.startOver}</button>
        </div>
      )}
    </div>
  )
}
