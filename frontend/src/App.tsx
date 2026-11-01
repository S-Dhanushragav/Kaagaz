import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  ApiError, askAudioUrl, askKaagaz, askSuggestions, claimSession, getMe, getSchemes, getSession, hasToken, myCheck, myChecks, setMyLanguage,
  setToken, startPhotos, startSample, startUpload,
  tickStep, type AskContext, type CatalogScheme, type Started, type CheckFull, type CheckSummary, type Language, type SessionView,
  type UserView,
} from './api'
import { play, stop, unlock } from './audio'
import { preparePhoto } from './photos'
import { STRINGS } from './i18n'
import AccountMenu from './ui/AccountMenu'
import { AskThread, Suggestions, type AskItem } from './ui/Ask'
import Chat, { type Answered, type Check } from './ui/Chat'
import { Camera, Menu, Mic, Person, Send } from './ui/Icons'
import LanguageMenu from './ui/LanguageMenu'
import Login from './ui/Login'
import PastCheck from './ui/PastCheck'
import SchemeCard from './ui/SchemeCard'
import Sidebar, { Wordmark } from './ui/Sidebar'
import { useVoiceAnswer } from './ui/voice'
import { useAskVoice } from './ui/askVoice'
import { MAX_SECONDS, clock } from './recording'

// Polls the session while it runs; `refresh` polls again after an answer or a close-up.
function useSession(id: string | null): { view: SessionView | null; error: string | null; refresh: () => void } {
  // Both are kept with the session id they belong to, so a new check never shows the last one's view.
  const [view, setView] = useState<SessionView | null>(null)
  const [error, setError] = useState<{ id: string; message: string } | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!id) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const v = await getSession(id)
        if (stopped) return
        setView(v)
        if (v.status === 'running') timer = setTimeout(poll, 1000)
      } catch (e) {
        if (!stopped) setError({ id, message: e instanceof Error ? e.message : String(e) })
      }
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [id, tick])
  return {
    view: id && view?.id === id ? view : null,
    error: id && error?.id === id ? error.message : null,
    refresh: useCallback(() => setTick((n) => n + 1), []),
  }
}

// Phones: the composer has less room, so a shorter placeholder.
function useNarrow(query = '(max-width: 859px)'): boolean {
  return useSyncExternalStore(
    (l) => { const m = window.matchMedia(query); m.addEventListener('change', l); return () => m.removeEventListener('change', l) },
    () => window.matchMedia(query).matches,
  )
}

type Center = { kind: 'live' } | { kind: 'past'; check: CheckFull; focus: number | null }

// Checks from this visit. "New check" (or the camera, or Check again) keeps the check on screen here, with the family's
// answers and the Ask thread, so it can be opened again while the server still has it (sessions last an hour).
// Kept in this tab only (sessionStorage), for guests and logged-in users alike.
export interface Visit {
  id: string; at: string; head: string | null
  check: Extract<Check, { kind: 'session' }>; answered: Answered[]; asks: AskItem[]
}
const VISIT_TTL_MS = 55 * 60 * 1000
function loadVisits(): Visit[] {
  try {
    const all = JSON.parse(sessionStorage.getItem('kaagaz.visits') ?? '[]') as Visit[]
    return all.filter((v) => Date.now() - Date.parse(v.at) < VISIT_TTL_MS)
  } catch {
    return []
  }
}

export default function App() {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem('kaagaz.lang') as Language) || 'mr')
  const [user, setUser] = useState<UserView | null>(null)
  const [authChecked, setAuthChecked] = useState(!hasToken()) // with a saved token: wait for /me (no guest flash)
  // Login is never the front door: it opens over the chat from "Log in" or the "Save this check" card.
  const [login, setLogin] = useState<{ claim: { id: string; secret: string } | null } | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [checks, setChecks] = useState<CheckSummary[]>([])
  const [latest, setLatest] = useState<CheckFull | null>(null)
  const [center, setCenter] = useState<Center>({ kind: 'live' })
  const [recheckOf, setRecheckOf] = useState<string | null>(null)
  const [check, setCheck] = useState<Check>({ kind: 'idle' })
  const [startError, setStartError] = useState<string | null>(null)
  const [answered, setAnswered] = useState<Answered[]>([])
  const [schemes, setSchemes] = useState<CatalogScheme[]>([])
  const [openScheme, setOpenScheme] = useState<string | null>(null)
  const [drawer, setDrawer] = useState(false)
  const [asks, setAsks] = useState<AskItem[]>([])
  const [visits, setVisits] = useState<Visit[]>(loadVisits)
  const [draft, setDraft] = useState('')
  const [suggestedFor, setSuggestedFor] = useState<{ key: string; items: string[] }>({ key: '', items: [] })
  const askCount = useRef(0)
  const t = STRINGS[language]
  const sessionId = check.kind === 'session' ? check.id : null
  const { view, error, refresh } = useSession(sessionId)
  const scroller = useRef<HTMLDivElement>(null)
  const narrow = useNarrow()

  // Ask Kaagaz: about the saved check on screen, or the live check once it has finished; else the 5 schemes only.
  const pastId = center.kind === 'past' ? center.check.id : null
  const liveDone = view?.status === 'done' ? sessionId : null
  const askContext: AskContext = useMemo(() => (pastId ? { checkId: pastId } : liveDone ? { sessionId: liveDone } : {}),
    [pastId, liveDone])
  const contextKey = pastId ?? liveDone ?? ''
  useEffect(() => {
    if (!contextKey) return
    let live = true
    askSuggestions(language, askContext).then((items) => { if (live) setSuggestedFor({ key: contextKey, items }) })
      .catch(() => { /* no suggestions: the box still works */ })
    return () => { live = false }
  }, [contextKey, askContext, language, view?.plan?.steps.length])
  const suggested = contextKey && suggestedFor.key === contextKey ? suggestedFor.items : []
  const asking = asks.some((a) => !a.reply && !a.error)
  // A spoken question: its words wait in the box with this ticket until the family taps Send.
  const [voiceTicket, setVoiceTicket] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const askVoice = useAskVoice(t, language, askContext, (text, result) => {
    setDraft(text)
    setVoiceTicket(result.voice_ticket)
    input.current?.focus()
  })
  const send = async (text: string) => {
    const question = text.trim()
    if (!question || asking) return
    const key = ++askCount.current
    const ticket = voiceTicket
    unlock()  // in the Send tap, so a spoken answer can play on a phone (iPhone Safari) seconds later
    setDraft('')
    setVoiceTicket(null)
    setAsks((a) => [...a, { key, context: contextKey, question, reply: null, error: null }])
    try {
      const reply = await askKaagaz(question, language, askContext, ticket)
      setAsks((a) => a.map((x) => (x.key === key ? { ...x, reply } : x)))
      if (ticket) play(`ask:${reply.id}`, askAudioUrl(reply.id))  // spoken questions get a spoken answer
    } catch (e) {
      const error = e instanceof ApiError && e.status === 429 ? e.message : t.askError
      setAsks((a) => a.map((x) => (x.key === key ? { ...x, error } : x)))
    }
  }

  useEffect(() => { sessionStorage.setItem('kaagaz.visits', JSON.stringify(visits)) }, [visits])

  useEffect(() => {
    localStorage.setItem('kaagaz.lang', language)
    document.documentElement.lang = language
  }, [language])

  useEffect(() => {
    let live = true
    getSchemes(language).then((s) => { if (live) setSchemes(s) }).catch(() => { /* the sidebar stays empty */ })
    return () => { live = false }
  }, [language])

  // The case file: the list, and the newest check in full (for "Welcome back").
  const loadChecks = useCallback(async () => {
    try {
      const list = await myChecks()
      setChecks(list)
      setLatest(list.length ? await myCheck(list[0].id) : null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setToken(null); setUser(null) }
    }
  }, [])

  useEffect(() => {
    if (!hasToken()) return
    getMe().then((u) => { setUser(u); void loadChecks() })
      .catch((e) => {
        // expired, signed with another key, or the user was deleted: forget it and land as a guest, no error.
        // Anything else (the case file is down): stay a guest for now and keep the token for next time.
        if (e instanceof ApiError && e.status === 401) setToken(null)
      })
      .finally(() => setAuthChecked(true))
  }, [loadChecks])

  // A logged-in check is saved when it finishes: refresh the list then.
  // (Not cancelled when the family moves on: the case file is the same whichever screen is showing.)
  useEffect(() => {
    if (!view?.check_id) return
    myChecks()
      .then((list) => { setChecks(list); return list.length ? myCheck(list[0].id) : null })
      .then((full) => setLatest(full))
      .catch(() => { /* the list refreshes next time */ })
  }, [view?.check_id, view?.plan?.steps.length])

  const onAnswered = useCallback((label: string) => {
    if (view?.question) setAnswered((a) => [...a, { question: view.question!.screen, member: view.question!.member, answer: label }])
    refresh()
  }, [view, refresh])
  const voice = useVoiceAnswer(t, sessionId, view?.status === 'waiting' ? view.question : null, onAnswered)

  // Follow the conversation as it grows (not on every poll: only when something new appears).
  const signature = [center.kind, check.kind, view?.status, view?.stage, view?.question?.question_id, answered.length,
    view?.recapture?.mode, view?.plan?.steps.length].join('|')
  useEffect(() => {
    const el = scroller.current
    if (el && center.kind === 'live') el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [signature, center.kind])
  const askSignature = asks.map((a) => `${a.key}${a.reply ? 'r' : a.error ? 'e' : ''}`).join('|')
  useEffect(() => {
    const el = scroller.current
    if (el && askSignature) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [askSignature])

  const begin = async (sample: boolean, start: () => Promise<Started>, photos = false) => {
    setStartError(null)
    setCheck({ kind: 'uploading', sample, percent: null, photos: photos ? { sent: 0, total: 0 } : null })
    try {
      const started = await start()
      setCheck({ kind: 'session', sample, id: started.id, guestSecret: started.guestSecret, photos })
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e))
      setCheck({ kind: 'idle' })
    }
  }
  const onSample = () => void begin(true, () => startSample(language, recheckOf))
  const onRecorded = (blob: Blob) => void begin(false, () => startUpload(blob, language,
    (percent) => setCheck((c) => (c.kind === 'uploading' ? { ...c, percent } : c)), recheckOf))
  // Photo mode: each photo is resized and re-encoded first (no EXIF leaves the phone), then all are sent at once.
  const onPhotosChosen = (files: File[]) => void begin(false, async () => {
    const photos = await Promise.all(files.map(preparePhoto))
    const progress = (sent: number, total: number) =>
      setCheck((c) => (c.kind === 'uploading' ? { ...c, photos: { sent, total } } : c))
    progress(0, photos.length)
    return startPhotos(photos, language, progress, recheckOf)
  }, true)
  // The live check on screen, kept in "Earlier in this visit" before something replaces it.
  const keep = (others: Visit[] = visits): Visit[] => {
    if (check.kind !== 'session' || center.kind !== 'live' || !view || view.status === 'error') return others
    const first = view.household?.members[0]
    const head = first ? (language === 'en' ? first.name_en ?? first.name_mr : first.name_mr ?? first.name_en) : null
    const earlier = others.find((v) => v.id === check.id)
    const visit: Visit = { id: check.id, at: earlier?.at ?? new Date().toISOString(), head, check, answered, asks }
    return [visit, ...others.filter((v) => v.id !== check.id)].slice(0, 5)
  }
  const openVisit = (id: string) => {
    const visit = visits.find((v) => v.id === id)
    if (!visit) return
    stop()
    setVisits(keep(visits).filter((v) => v.id !== id).concat(visit).sort((a, b) => b.at.localeCompare(a.at)))
    setCheck(visit.check)
    setAnswered(visit.answered)
    setAsks(visit.asks)
    setStartError(null)
    setRecheckOf(null)
    setCenter({ kind: 'live' })
    setDrawer(false)
  }
  const newCheck = () => {
    setVisits(keep())
    stop()
    setCheck({ kind: 'idle' })
    setAnswered([])
    setStartError(null)
    setRecheckOf(null)
    setCenter({ kind: 'live' })
    setDrawer(false)
    setAsks([])
  }

  const openCheck = async (id: string, focus: number | null = null) => {
    stop()
    setDrawer(false)
    setAsks([])
    try {
      setCenter({ kind: 'past', check: await myCheck(id), focus })
      scroller.current?.scrollTo({ top: 0 })
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e))
    }
  }

  const onTick = async (step: number, done: boolean) => {
    if (center.kind !== 'past') return
    const id = center.check.id
    setCenter({ ...center, check: { ...center.check, steps_done: { ...center.check.steps_done, [String(step)]: done } } })
    const was = !!center.check.steps_done[String(step)]
    if (was !== done) {  // the list follows at once; the server's numbers replace these when it answers
      setChecks((list) => list.map((c) => (c.id === id ? { ...c, open_steps: c.open_steps + (done ? -1 : 1) } : c)))
    }
    try {
      const s = await tickStep(id, step, done)
      setChecks((list) => list.map((c) => (c.id === id ? s : c)))
      if (latest?.id === id) setLatest({ ...latest, ...s, steps_done: { ...latest.steps_done, [String(step)]: done } })
    } catch {
      void openCheck(id)  // show what is really stored
    }
  }

  const checkAgain = (sample: boolean, photos = false) => {
    if (center.kind !== 'past') return
    const id = center.check.id
    newCheck()
    setRecheckOf(id)
    if (sample) void begin(true, () => startSample(language, id))
    else setCheck({ kind: photos ? 'photos' : 'recording' })
  }
  // An answer's "Add a photo" chip for a document there is no close-up for: add photos (of a saved check: check again).
  const addPhotos = () => {
    if (center.kind === 'past') checkAgain(false, true)
    else { newCheck(); setCheck({ kind: 'photos' }) }
  }

  const changeLanguage = (l: Language) => {
    setLanguage(l)
    if (user) setMyLanguage(l).then(setUser).catch(() => { /* kept locally anyway */ })
  }

  const signedOut = (note: string | null) => {
    setToken(null)
    setUser(null)
    setChecks([])
    setLatest(null)
    setFlash(note)
    newCheck()
  }

  const loggedIn = async (token: string, u: UserView) => {
    setToken(token)
    setUser(u)
    setFlash(null)
    const claim = login?.claim ?? null
    setLogin(null)
    if (claim) {
      try {
        await claimSession(claim.id, claim.secret)  // the guest check this login was for
      } catch {
        setFlash(t.saveFailed)  // e.g. the case file is down: the check itself still works here
      }
    }
    await loadChecks()  // "Your checks" shows it at once (a check still running is listed when it finishes)
    if (claim) refresh()  // the session view now carries the saved check id
  }

  if (!authChecked) return null

  const busy = check.kind === 'recording' || check.kind === 'uploading' || view?.status === 'running' || view?.status === 'waiting'
  const scheme = schemes.find((s) => s.id === openScheme)

  return (
    <div className="shell">
      <aside className={drawer ? 'side open' : 'side'}>
        <Sidebar t={t} language={language} schemes={schemes} onNewCheck={newCheck}
          onOpenScheme={(id) => { setOpenScheme(id); setDrawer(false) }} onClose={() => setDrawer(false)}
          user={user} checks={checks} openCheck={center.kind === 'past' ? center.check.id : null}
          visits={visits} openVisit={center.kind === 'live' && check.kind === 'session' ? check.id : null}
          onOpenVisit={openVisit}
          onOpenCheck={(id) => void openCheck(id)} onLogin={() => { setDrawer(false); setLogin({ claim: null }) }} />
      </aside>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}

      <main className="center">
        <header className="topbar">
          <button type="button" className="icon-button only-narrow" aria-label={t.menu} onClick={() => setDrawer(true)}><Menu /></button>
          <div className="only-narrow"><Wordmark t={t} /></div>
          <div className="topbar-right">
            <LanguageMenu t={t} language={language} onChange={changeLanguage} />
            {user ? (
              <AccountMenu t={t} user={user} language={language} onLanguage={changeLanguage}
                onLogout={() => signedOut(null)} onDeleted={() => signedOut(t.deletedNote)} />
            ) : (
              <button type="button" className="account-button" onClick={() => setLogin({ claim: null })}>
                <Person /><span>{t.logIn}</span>
              </button>
            )}
          </div>
        </header>

        <div className="conversation" ref={scroller}>
          <div className="conversation-inner">
            {flash && <p className="flash" role="status">{flash}</p>}
            {center.kind === 'past' ? (
              <PastCheck t={t} language={language} check={center.check} schemes={schemes} focus={center.focus}
                onTick={(s, d) => void onTick(s, d)} onCheckAgain={checkAgain} narrow={narrow} onOpenScheme={setOpenScheme} />
            ) : (
              <Chat t={t} language={language} schemes={schemes} check={check} view={view} error={startError ?? error}
                answered={answered} voice={voice} onRecord={() => setCheck({ kind: 'recording' })}
                onPhotos={() => setCheck({ kind: 'photos' })} onSample={onSample} onRecorded={onRecorded}
                onPhotosChosen={onPhotosChosen} onCancelRecord={() => setCheck({ kind: 'idle' })} onAnswered={onAnswered}
                onReplanned={refresh} onNewCheck={newCheck} recheck={recheckOf !== null}
                onRecordAgain={() => { newCheck(); setCheck({ kind: 'recording' }) }}
                onPhotosAgain={() => { newCheck(); setCheck({ kind: 'photos' }) }}
                latest={user && latest && latest.id === checks[0]?.id ? latest : null /* never an older check while the newest loads */}
                onOpenCheck={(id, step) => void openCheck(id, step)} loggedIn={user !== null}
                onSaveCheck={() => { if (check.kind === 'session') setLogin({ claim: { id: check.id, secret: check.guestSecret } }) }}
                narrow={narrow} onOpenScheme={setOpenScheme}
                beforeCheck={<AskThread t={t} items={asks.filter((a) => !a.context)} sessionId={null} sample={false}
                  onReplanned={refresh} onAddPhotos={addPhotos} />} />
            )}
            {!asks.some((a) => a.context === contextKey) && <Suggestions t={t} items={suggested} onPick={(q) => void send(q)} />}
            <AskThread t={t} items={center.kind === 'past' ? asks : asks.filter((a) => a.context)}
              sessionId={askContext.sessionId ?? null} sample={!!view?.sample} onReplanned={refresh} onAddPhotos={addPhotos} />
          </div>
        </div>

        {(askVoice.phase !== 'idle' || askVoice.note || voiceTicket) && (
          <div className="voice-panel" role="status" aria-live="polite" data-stt-ms={askVoice.lastMs ?? undefined}>
            {askVoice.phase === 'listening' && (
              <>
                <span className="rec-dot" aria-hidden="true" />
                <span className="voice-text">{t.askListening}</span>
                <span className="rec-time">{clock(askVoice.seconds)} / {clock(MAX_SECONDS)}</span>
                <span className="level" aria-hidden="true"><span style={{ width: `${Math.round(askVoice.level * 100)}%` }} /></span>
              </>
            )}
            {askVoice.phase === 'writing' && <span className="voice-text">{t.askWriting}</span>}
            {askVoice.phase === 'idle' && (askVoice.note
              ? <span className="voice-text note">{askVoice.note}</span>
              : <span className="voice-text">{t.askCheckText}</span>)}
          </div>
        )}
        <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(draft) }}>
          <label className="composer-field">
            <span className="sr-only">{t.askPlaceholder}</span>
            <input ref={input} type="text" placeholder={narrow ? t.askShort : t.askPlaceholder} value={draft} maxLength={500}
              enterKeyHint="send" onChange={(e) => { setDraft(e.target.value); if (!e.target.value) setVoiceTicket(null) }} />
          </label>
          {/* The mic answers the family question while one is waiting; otherwise it asks Kaagaz. */}
          {voice.allowed ? (
            <button type="button" className={voice.listening ? 'round-button listening' : 'round-button'}
              aria-label={voice.listening ? t.listening : t.speak} disabled={voice.busy && !voice.listening}
              onClick={voice.toggle}><Mic /></button>
          ) : (
            <button type="button" className={askVoice.phase === 'listening' ? 'round-button listening' : 'round-button'}
              aria-label={askVoice.phase === 'listening' ? t.askListening : t.askByVoice}
              aria-pressed={askVoice.phase === 'listening'} disabled={askVoice.phase === 'writing' || asking}
              onClick={() => { unlock(); askVoice.toggle() }}><Mic /></button>
          )}
          <button type="button" className="round-button" aria-label={t.camera} disabled={busy}
            onClick={() => { newCheck(); setCheck({ kind: 'recording' }) }}><Camera /></button>
          <button type="submit" className="round-button primary" aria-label={t.send} disabled={!draft.trim() || asking}><Send /></button>
        </form>
      </main>

      {scheme && <SchemeCard key={scheme.id} t={t} scheme={scheme} onClose={() => setOpenScheme(null)} />}
      {login && (
        <div className="login-overlay">
          <Login t={t} language={language} setLanguage={changeLanguage} onLoggedIn={(token, u) => void loggedIn(token, u)}
            onGuest={() => setLogin(null)} />
        </div>
      )}
    </div>
  )
}
