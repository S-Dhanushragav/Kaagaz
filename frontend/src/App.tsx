import { useCallback, useEffect, useRef, useState } from 'react'
import {
  answerAudio, answerOption, audioUrl, getSession, startSample, startUpload,
  type Language, type Member, type Question, type SessionView, type Shown, type Step, type StepDisplay,
} from './api'
import { LANGUAGE_NAMES, STRINGS, type Strings } from './i18n'
import { toWav16k } from './wav'

type Screen = { name: 'home' } | { name: 'record' } | { name: 'uploading' } | { name: 'session'; id: string }

const MAX_RECORD_S = 45
const VIDEO_BITS_PER_SECOND = 4_000_000 // 720p cap: ~22 MB for 45 s (server limit 60 MB)

// ---------- audio playback: one sentence at a time ----------

let current: HTMLAudioElement | null = null
function play(url: string): void {
  current?.pause()
  current = new Audio(url)
  void current.play().catch(() => { /* autoplay blocked or no TTS on the server */ })
}

function PlayButton({ url, t }: { url: string; t: Strings }) {
  return <button type="button" className="play" onClick={() => play(url)} aria-label={t.play}>▶ {t.play}</button>
}

// ---------- app ----------

export default function App() {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem('kaagaz.lang') as Language) || 'mr')
  const [screen, setScreen] = useState<Screen>({ name: 'home' })
  const [error, setError] = useState<string | null>(null)
  const t = STRINGS[language]

  useEffect(() => {
    localStorage.setItem('kaagaz.lang', language)
    document.documentElement.lang = language
  }, [language])

  const run = useCallback(async (start: () => Promise<string>) => {
    setError(null)
    try {
      setScreen({ name: 'uploading' })
      setScreen({ name: 'session', id: await start() })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setScreen({ name: 'home' })
    }
  }, [])

  return (
    <div className="app">
      <header>
        <h1>{t.appName}</h1>
        <p className="specimen" role="note">{t.specimen}</p>
      </header>
      {error && <p className="error" role="alert">{t.error}: {error}</p>}
      {screen.name === 'home' && (
        <Home t={t} language={language} setLanguage={setLanguage}
          onSample={() => run(() => startSample(language))} onRecord={() => setScreen({ name: 'record' })} />
      )}
      {screen.name === 'record' && (
        <Recorder t={t} onDone={(blob) => run(() => startUpload(blob, language))} onCancel={() => setScreen({ name: 'home' })} />
      )}
      {screen.name === 'uploading' && <p className="status" aria-live="polite">{t.uploading}</p>}
      {screen.name === 'session' && (
        <SessionScreen t={t} id={screen.id} language={language} onRestart={() => setScreen({ name: 'home' })} />
      )}
    </div>
  )
}

// ---------- home ----------

function Home({ t, language, setLanguage, onSample, onRecord }: {
  t: Strings; language: Language; setLanguage: (l: Language) => void; onSample: () => void; onRecord: () => void
}) {
  return (
    <main>
      <p className="lead">{t.tagline}</p>
      <h2>{t.chooseLanguage}</h2>
      <div className="languages" role="radiogroup" aria-label={t.chooseLanguage}>
        {(['mr', 'hi', 'en'] as Language[]).map((l) => (
          <button key={l} type="button" role="radio" aria-checked={language === l}
            className={language === l ? 'choice selected' : 'choice'} onClick={() => setLanguage(l)}>
            {LANGUAGE_NAMES[l]}
          </button>
        ))}
      </div>
      <button type="button" className="primary" onClick={onSample}>{t.trySample}</button>
      <button type="button" className="secondary" onClick={onRecord}>{t.record}</button>
    </main>
  )
}

// ---------- recording the sweep ----------

function pickVideoType(): string | undefined {
  return ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4']
    .find((type) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type))
}

function Recorder({ t, onDone, onCancel }: { t: Strings; onDone: (b: Blob) => void; onCancel: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const [recording, setRecording] = useState(false)
  const [left, setLeft] = useState(MAX_RECORD_S)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    navigator.mediaDevices?.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
    }).then((stream) => {
      if (cancelled) { stream.getTracks().forEach((tr) => tr.stop()); return }
      streamRef.current = stream
      if (videoRef.current) videoRef.current.srcObject = stream
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
    return <main><p className="error">{t.cameraError}</p><button type="button" className="secondary" onClick={onCancel}>{t.startOver}</button></main>
  }
  return (
    <main>
      {!recording && (
        <section className="card">
          <h2>{t.guidanceTitle}</h2>
          <ol className="guidance">{t.guidance.map((g) => <li key={g}>{g}</li>)}</ol>
        </section>
      )}
      <video ref={videoRef} className="preview" autoPlay playsInline muted />
      {recording ? (
        <>
          <p className="timer" aria-live="polite">{left} {t.secondsLeft}</p>
          <button type="button" className="primary danger" onClick={() => recorderRef.current?.stop()}>■ {t.stopRecording}</button>
        </>
      ) : (
        <>
          <button type="button" className="primary" onClick={start}>● {t.startRecording}</button>
          <button type="button" className="secondary" onClick={onCancel}>{t.startOver}</button>
        </>
      )}
    </main>
  )
}

// ---------- a running session ----------

function SessionScreen({ t, id, language, onRestart }: { t: Strings; id: string; language: Language; onRestart: () => void }) {
  const [view, setView] = useState<SessionView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const v = await getSession(id)
        if (stop) return
        setView(v)
        if (v.status === 'running') timer = setTimeout(poll, 1000)
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : String(e))
      }
    }
    void poll()
    return () => { stop = true; clearTimeout(timer) }
  }, [id, tick])

  const resumed = () => setTick((n) => n + 1) // poll again after an answer

  if (error) return <main><p className="error">{t.error}: {error}</p><button type="button" className="secondary" onClick={onRestart}>{t.startOver}</button></main>
  if (!view) return <main><p className="status">{t.working}…</p></main>
  if (view.status === 'done' && view.recapture?.mode === 'sweep_again') {
    // Most documents unreadable: no plan or results built on them; only the request to record again.
    return <main><Recapture t={t} view={view} /><button type="button" className="primary" onClick={onRestart}>{t.startOver}</button></main>
  }
  return (
    <main>
      {view.status === 'error' && <p className="error" role="alert">{t.error}: {view.error}</p>}
      {view.status !== 'done' && <Progress t={t} view={view} />}
      {view.status === 'waiting' && view.question && (
        <QuestionCard key={view.question.question_id} t={t} id={id} question={view.question} onAnswered={resumed} />
      )}
      <Recapture t={t} view={view} />
      {view.status === 'done' && view.recapture?.mode === 'close_ups' && <p className="note">{t.closeUpsNote}</p>}
      {view.status === 'done' && <Plan t={t} id={id} view={view} />}
      {view.household && <Results t={t} view={view} language={language} />}
      <button type="button" className="secondary" onClick={onRestart}>{t.startOver}</button>
    </main>
  )
}

function Progress({ t, view }: { t: Strings; view: SessionView }) {
  return (
    <section className="card" aria-live="polite">
      <h2>{t.working}</h2>
      <ol className="stages">
        {view.stages.map((s) => (
          <li key={s.stage} className={s.done ? 'done' : view.stage === s.stage ? 'active' : 'todo'}>
            <span className="mark" aria-hidden="true">{s.done ? '✓' : view.stage === s.stage ? '…' : '○'}</span>
            {t.stages[s.stage]}
            {s.done && s.seconds !== null && <span className="secs"> {s.seconds.toFixed(0)} s</span>}
          </li>
        ))}
      </ol>
    </section>
  )
}

// ---------- questions: big numbered buttons first, voice as a bonus ----------

function QuestionCard({ t, id, question, onAnswered }: { t: Strings; id: string; question: Question; onAnswered: () => void }) {
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [micAllowed, setMicAllowed] = useState(true)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const confirm = question.severity === 'confirm' || question.kind === 'compare'

  const choose = async (option: number) => {
    setBusy(true)
    try { await answerOption(id, question.question_id, option); onAnswered() } catch (e) { setNote(String(e)); setBusy(false) }
  }

  const toggleMic = async () => {
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
          const reply = await answerAudio(id, question.question_id, await toWav16k(new Blob(chunks, { type: recorder.mimeType })))
          if (reply.action === 'answered') { onAnswered(); return }
          setNote(reply.action === 'ask_again' ? t.notUnderstood : t.useButtons)
          if (reply.action === 'show_buttons') setMicAllowed(false)
        } catch {
          setNote(t.useButtons)
          setMicAllowed(false)
        }
        setBusy(false)
      }
      recorderRef.current = recorder
      recorder.start()
      setListening(true)
      setTimeout(() => { if (recorder.state === 'recording') recorder.stop() }, 6000)
    } catch {
      setMicAllowed(false)
    }
  }

  return (
    <section className="card question" aria-live="polite">
      <h2>{confirm ? t.confirmTitle : t.questionTitle}</h2>
      {question.member && <p className="member">{question.member}</p>}
      <div className="side-by-side">
        {question.values.map((v, i) => (
          <div key={i} className="spelling"><span className="doc">{t.docTypes[v.document_type] ?? v.document_type}</span><strong>{v.value}</strong></div>
        ))}
      </div>
      <PlayButton url={audioUrl(id, 'question')} t={t} />
      <div className="options">
        {question.shown.map((label, i) => (
          <button key={i} type="button" className="option" disabled={busy} onClick={() => choose(i)}>
            <span className="num">{i + 1}</span><span>{label}</span>
          </button>
        ))}
      </div>
      {micAllowed && (
        <button type="button" className={listening ? 'mic listening' : 'mic'} disabled={busy && !listening} onClick={toggleMic}>
          🎤 {listening ? t.listening : t.mic}
        </button>
      )}
      {note && <p className="note" role="status">{note}</p>}
    </section>
  )
}

// ---------- recapture ----------

function Recapture({ t, view }: { t: Strings; view: SessionView }) {
  const r = view.recapture
  if (!r || r.mode === 'none') return null
  const docType = (docId: string) => view.household?.documents[docId]?.doc_type
  return (
    <section className={r.mode === 'sweep_again' ? 'card warn strong' : 'card warn'}>
      {r.mode === 'sweep_again' ? <p>{t.recaptureSweep}</p> : (
        <>
          <p>{t.recaptureCloseUps}</p>
          <ul>{r.documents.map((d) => <li key={d}>{t.docTypes[docType(d) ?? ''] ?? d}</li>)}</ul>
        </>
      )}
    </section>
  )
}

// ---------- the plan ----------

function Fact({ t, shown }: { t: Strings; shown: Shown }) {
  return <>{shown.text}{!shown.verified && <span className="unverified"> ({t.unverified})</span>}</>
}

function Plan({ t, id, view }: { t: Strings; id: string; view: SessionView }) {
  const steps = view.plan?.steps ?? []
  const display = (i: number): StepDisplay | null => view.speech?.[i]?.display ?? null
  if (!steps.length) return <section className="card"><h2>{t.planTitle}</h2><p>{t.noPlan}</p></section>
  const visits = new Map<number, number[]>()
  steps.forEach((s, i) => { if (s.kind === 'fix' && s.visit) visits.set(s.visit, [...(visits.get(s.visit) ?? []), i]) })
  const asked = steps.map((s, i) => [s, i] as const).filter(([s]) => s.kind === 'question')
  const office = steps.map((s, i) => [s, i] as const).filter(([s]) => s.kind === 'ask_at_office')
  return (
    <section className="card plan">
      <h2>{t.planTitle}</h2>
      {[...visits.entries()].sort(([a], [b]) => a - b).map(([visit, idx]) => (
        <div key={visit} className="visit">
          <h3>{t.visit} {visit}{display(idx[0])?.office && <>: <Fact t={t} shown={display(idx[0])!.office!} /></>}</h3>
          {idx.map((i) => <FixStep key={i} t={t} id={id} step={steps[i]} index={i} display={display(i)} />)}
        </div>
      ))}
      {office.length > 0 && (
        <div className="visit">
          <h3>{t.askAtOffice}</h3>
          {office.map(([s, i]) => <FixStep key={i} t={t} id={id} step={s} index={i} display={null} />)}
        </div>
      )}
      {asked.length > 0 && (
        <details>
          <summary>{t.questionsAsked}</summary>
          {asked.map(([s, i]) => <p key={i}>{s.question} → <strong>{s.answer}</strong></p>)}
        </details>
      )}
    </section>
  )
}

function FixStep({ t, id, step, index, display }: { t: Strings; id: string; step: Step; index: number; display: StepDisplay | null }) {
  const download = () => {
    const url = URL.createObjectURL(new Blob([step.declaration ?? ''], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'declaration-draft.txt'
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="step">
      <p className="voice">{step.voice}</p>
      <PlayButton url={audioUrl(id, `step-${index}`)} t={t} />
      {display && (display.bring.length > 0 || display.fee || display.time_limit) && (
        <dl>
          {display.bring.map((b) => <div key={b.text}><dt>{t.bring}</dt><dd><Fact t={t} shown={b} /></dd></div>)}
          {display.fee && <div><dt>{t.fee}</dt><dd><Fact t={t} shown={display.fee} /></dd></div>}
          {display.time_limit && <div><dt>{t.timeLimit}</dt><dd><Fact t={t} shown={display.time_limit} /></dd></div>}
        </dl>
      )}
      {step.declaration && <button type="button" className="secondary" onClick={download}>⬇ {t.downloadDeclaration}</button>}
    </div>
  )
}

// ---------- results ----------

function memberName(m: Member, language: Language, t: Strings): string {
  const name = language === 'en' ? m.name_en ?? m.name_mr : m.name_mr ?? m.name_en
  if (name) return name
  return m.on_ration_card ? t.cardMember.replace('{n}', m.member_id.replace(/^r/, '')) : t.personNotOnCard
}

function Results({ t, view, language }: { t: Strings; view: SessionView; language: Language }) {
  const hh = view.household!
  const byMember = new Map<string, NonNullable<SessionView['results']>>()
  for (const r of view.results ?? []) byMember.set(r.member_id, [...(byMember.get(r.member_id) ?? []), r])
  const problems = hh.issues.filter((i) => i.severity !== 'info')
  return (
    <>
      <section className="card">
        <h2>{t.documentsTitle}</h2>
        <ul className="docs">
          {Object.values(hh.documents).map((d) => (
            <li key={d.document_id}>{t.docTypes[d.doc_type ?? ''] ?? d.doc_type ?? '?'}{d.unreadable ? ` (${t.issueTypes.unreadable})` : ''}</li>
          ))}
        </ul>
      </section>
      <section className="card">
        <h2>{t.issuesTitle}</h2>
        {problems.length === 0 ? <p>{t.noIssues}</p> : (
          <ul className="issues">
            {problems.map((i, n) => {
              const m = hh.members.find((x) => x.member_id === i.member_id)
              return <li key={n} className={i.severity}>{t.issueTypes[i.type] ?? i.type}{m ? `: ${memberName(m, language, t)}` : ''}</li>
            })}
          </ul>
        )}
      </section>
      <section className="card">
        <h2>{t.householdTitle}</h2>
        {hh.members.map((m) => (
          <div key={m.member_id} className="member-card">
            <h3>{memberName(m, language, t)}{!m.on_ration_card && <span className="tag"> {t.notOnCard}</span>}</h3>
            <p className="small">{Object.keys(m.documents).map((d) => t.docTypes[d] ?? d).join(', ')}</p>
            <ul className="schemes">
              {(byMember.get(m.member_id) ?? []).map((r) => (
                <li key={r.scheme_id} className={`outcome ${r.outcome}`}>
                  <details>
                    <summary><strong>{r.scheme_name}</strong>: {t.outcomes[r.outcome]}</summary>
                    <ul className="small">{r.reasons.map((x, n) => <li key={n}>{x}</li>)}</ul>
                    <p className="small">{t.sources}: {r.rules.filter((x) => x.source_url).map((x, n) => (
                      <a key={n} href={x.source_url!} target="_blank" rel="noreferrer">{x.source}</a>
                    ))}</p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </>
  )
}
