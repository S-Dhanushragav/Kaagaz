// Asking by voice (push-to-talk): tap the mic to start and again to stop (at most 30 s), with a timer and a live level
// meter. The clip (WebM/Opus on Android Chrome, MP4/AAC on iPhone Safari) is sent once; the backend writes it down and
// the words go into the box for the family to check. Nothing is sent to Ask Kaagaz until they tap Send.
import { useEffect, useRef, useState } from 'react'
import { ApiError, transcribeQuestion, type AskContext, type Language, type Transcribed } from '../api'
import type { Strings } from '../i18n'
import { MAX_SECONDS, meterLevel, micErrorNote, pickMimeType } from '../recording'

const QUIET = 0.1 // peak meter level (0-1, about -55 dBFS) below which the whole clip counts as silence

export type Phase = 'idle' | 'listening' | 'writing'

export interface AskVoice {
  phase: Phase
  seconds: number
  level: number // 0-1, live while listening
  note: string | null
  lastMs: number | null // from tapping stop to the words in the box (for timings)
  toggle: () => void
}

export function useAskVoice(t: Strings, language: Language, context: AskContext,
  onText: (text: string, result: Transcribed) => void): AskVoice {
  const [phase, setPhase] = useState<Phase>('idle')
  const [seconds, setSeconds] = useState(0)
  const [level, setLevel] = useState(0)
  const [note, setNote] = useState<string | null>(null)
  const [lastMs, setLastMs] = useState<number | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const cleanup = useRef<(() => void) | null>(null)

  useEffect(() => () => cleanup.current?.(), [])

  const start = async () => {
    setNote(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') { setNote(t.noMic); return }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    } catch (e) {
      setNote(micErrorNote(t, e))
      return
    }
    const mimeType = pickMimeType((m) => MediaRecorder.isTypeSupported(m))
    const rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    const chunks: Blob[] = []
    let peak = 0
    // live level meter: the RMS of what the mic hears, about 30 times a second
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    ctx.createMediaStreamSource(stream).connect(analyser)
    const samples = new Float32Array(analyser.fftSize)
    let frame = 0
    const meter = () => {
      analyser.getFloatTimeDomainData(samples)
      const rms = Math.sqrt(samples.reduce((s, x) => s + x * x, 0) / samples.length)
      const shown = meterLevel(rms)
      peak = Math.max(peak, shown)
      setLevel(shown)
      frame = requestAnimationFrame(meter)
    }
    frame = requestAnimationFrame(meter)
    const began = Date.now()
    const timer = setInterval(() => {
      const s = (Date.now() - began) / 1000
      setSeconds(s)
      if (s >= MAX_SECONDS && rec.state === 'recording') rec.stop()
    }, 200)
    const release = () => {
      clearInterval(timer)
      cancelAnimationFrame(frame)
      stream.getTracks().forEach((tr) => tr.stop())
      void ctx.close()
      cleanup.current = null
    }
    cleanup.current = () => { if (rec.state === 'recording') rec.stop(); release() }
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
    rec.onstop = async () => {
      release()
      setLevel(0)
      const stopped = performance.now()
      const clip = new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' })
      if (!clip.size || peak < QUIET) { setPhase('idle'); setNote(t.silentRecording); return }
      setPhase('writing')
      try {
        const result = await transcribeQuestion(clip, language, context)
        setLastMs(Math.round(performance.now() - stopped))
        setPhase('idle')
        onText(result.text, result)
      } catch (e) {
        setPhase('idle')
        if (e instanceof ApiError && e.code === 'silent') setNote(t.silentRecording)
        else if (e instanceof ApiError && e.status === 429) setNote(e.message)
        else setNote(t.voiceFailed)
      }
    }
    recorder.current = rec
    rec.start()
    setSeconds(0)
    setPhase('listening')
  }

  const toggle = () => {
    if (phase === 'listening') { recorder.current?.stop(); return }
    if (phase === 'idle') void start()
  }

  return { phase, seconds, level, note, lastMs, toggle }
}
