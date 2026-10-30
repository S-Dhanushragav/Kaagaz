// Answering the pending question by voice. One hook per question, shared by the question card's mic and the
// composer's mic, so both show the same state.
import { useRef, useState } from 'react'
import { answerAudio, type Question } from '../api'
import type { Strings } from '../i18n'
import { toWav16k } from '../wav'

export interface Voice {
  listening: boolean
  busy: boolean
  note: string | null
  allowed: boolean // false once the server asks for buttons, or the mic is refused
  toggle: () => void
}

export function useVoiceAnswer(t: Strings, sessionId: string | null, question: Question | null, onAnswered: (label: string) => void): Voice {
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [blocked, setBlocked] = useState<string | null>(null) // question id the mic is switched off for
  const recorderRef = useRef<MediaRecorder | null>(null)
  const allowed = !!question && blocked !== question.question_id

  const toggle = async () => {
    if (!sessionId || !question) return
    if (listening) { recorderRef.current?.stop(); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      const chunks: Blob[] = []
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
      recorder.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop())
        setListening(false)
        setBusy(true)
        try {
          const reply = await answerAudio(sessionId, question.question_id, await toWav16k(new Blob(chunks, { type: recorder.mimeType })))
          if (reply.action === 'answered' && reply.option !== null) {
            setNote(null)
            setBusy(false)
            onAnswered(question.shown[reply.option] ?? '')
            return
          }
          setNote(reply.action === 'ask_again' ? t.notUnderstood : t.useButtons)
          if (reply.action === 'show_buttons') setBlocked(question.question_id)
        } catch {
          setNote(t.useButtons)
          setBlocked(question.question_id)
        }
        setBusy(false)
      }
      recorderRef.current = recorder
      setNote(null)
      recorder.start()
      setListening(true)
      setTimeout(() => { if (recorder.state === 'recording') recorder.stop() }, 6000)
    } catch {
      setBlocked(question.question_id)
    }
  }

  return { listening, busy, note, allowed, toggle: () => { void toggle() } }
}
