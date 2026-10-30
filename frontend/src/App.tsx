import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  ApiError, claimSession, getMe, getSchemes, getSession, hasToken, myCheck, myChecks, setMyLanguage, setToken, startSample, startUpload,
  tickStep, type CatalogScheme, type CheckFull, type CheckSummary, type Language, type SessionView, type UserView,
} from './api'
import { stop } from './audio'
import { STRINGS } from './i18n'
import AccountMenu from './ui/AccountMenu'
import Chat, { type Answered, type Check } from './ui/Chat'
import HouseholdPanel from './ui/HouseholdPanel'
import { Camera, Family, Menu, Mic, Person, Send } from './ui/Icons'
import LanguageMenu from './ui/LanguageMenu'
import Login from './ui/Login'
import { checkAsView } from './casefile'
import PastCheck from './ui/PastCheck'
import SchemeCard from './ui/SchemeCard'
import Sidebar, { Wordmark } from './ui/Sidebar'
import { useVoiceAnswer } from './ui/voice'

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

export default function App() {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem('kaagaz.lang') as Language) || 'mr')
  const [user, setUser] = useState<UserView | null>(null)
  const [authChecked, setAuthChecked] = useState(!hasToken()) // with a saved token: wait for /me (no guest flash)
  // Login is never the front door: it opens over the chat from "Log in" or the "Save this check" card.
  const [login, setLogin] = useState<{ claim: string | null } | null>(null)
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
  const [sheet, setSheet] = useState(false)
  const t = STRINGS[language]
  const sessionId = check.kind === 'session' ? check.id : null
  const { view, error, refresh } = useSession(sessionId)
  const scroller = useRef<HTMLDivElement>(null)
  const narrow = useNarrow()

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
      .catch(() => setToken(null))
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

  const begin = async (sample: boolean, start: () => Promise<string>) => {
    setStartError(null)
    setCheck({ kind: 'uploading', sample, percent: null })
    try {
      setCheck({ kind: 'session', sample, id: await start() })
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e))
      setCheck({ kind: 'idle' })
    }
  }
  const onSample = () => void begin(true, () => startSample(language, recheckOf))
  const onRecorded = (blob: Blob) => void begin(false, () => startUpload(blob, language,
    (percent) => setCheck((c) => (c.kind === 'uploading' ? { ...c, percent } : c)), recheckOf))
  const newCheck = () => {
    stop()
    setCheck({ kind: 'idle' })
    setAnswered([])
    setStartError(null)
    setRecheckOf(null)
    setCenter({ kind: 'live' })
    setDrawer(false)
    setSheet(false)
  }

  const openCheck = async (id: string, focus: number | null = null) => {
    stop()
    setDrawer(false)
    setSheet(false)
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

  const checkAgain = (sample: boolean) => {
    if (center.kind !== 'past') return
    const id = center.check.id
    newCheck()
    setRecheckOf(id)
    if (sample) void begin(true, () => startSample(language, id))
    else setCheck({ kind: 'recording' })
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
        await claimSession(claim)  // the guest check this login was for
        refresh()  // the session view now carries the saved check id
      } catch (e) {
        setStartError(e instanceof Error ? e.message : String(e))
      }
    }
    void loadChecks()
  }

  if (!authChecked) return null

  const busy = check.kind === 'recording' || check.kind === 'uploading' || view?.status === 'running' || view?.status === 'waiting'
  const scheme = schemes.find((s) => s.id === openScheme)
  const panelView = center.kind === 'past' ? checkAsView(center.check) : view
  const members = panelView?.household?.members.length ?? 0

  return (
    <div className="shell">
      <aside className={drawer ? 'side open' : 'side'}>
        <Sidebar t={t} language={language} schemes={schemes} onNewCheck={newCheck}
          onOpenScheme={(id) => { setOpenScheme(id); setDrawer(false) }} onClose={() => setDrawer(false)}
          user={user} checks={checks} openCheck={center.kind === 'past' ? center.check.id : null}
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
                onTick={(s, d) => void onTick(s, d)} onCheckAgain={checkAgain} />
            ) : (
              <Chat t={t} language={language} schemes={schemes} check={check} view={view} error={startError ?? error}
                answered={answered} voice={voice} onRecord={() => setCheck({ kind: 'recording' })} onSample={onSample}
                onRecorded={onRecorded} onCancelRecord={() => setCheck({ kind: 'idle' })} onAnswered={onAnswered}
                onReplanned={refresh} onNewCheck={newCheck} recheck={recheckOf !== null}
                latest={user && latest && latest.id === checks[0]?.id ? latest : null /* never an older check while the newest loads */}
                onOpenCheck={(id, step) => void openCheck(id, step)} loggedIn={user !== null}
                onSaveCheck={(id) => setLogin({ claim: id })} />
            )}
          </div>
        </div>

        {members > 0 && (
          <button type="button" className="family-bar only-sheet" onClick={() => setSheet(true)}>
            <Family /><span>{t.householdTitle}</span><span className="family-count">{t.familyCount.replace('{n}', String(members))}</span>
          </button>
        )}

        <form className="composer" onSubmit={(e) => e.preventDefault()}>
          {/* Ask Kaagaz is wired in Phase 10. */}
          <label className="composer-field">
            <span className="sr-only">{t.askPlaceholder}</span>
            <input type="text" placeholder={narrow ? t.askShort : t.askPlaceholder} disabled />
            <span className="soon">{t.soon}</span>
          </label>
          <button type="button" className={voice.listening ? 'round-button listening' : 'round-button'}
            aria-label={voice.listening ? t.listening : t.speak} disabled={!voice.allowed || (voice.busy && !voice.listening)}
            onClick={voice.toggle}><Mic /></button>
          <button type="button" className="round-button" aria-label={t.camera} disabled={busy}
            onClick={() => { newCheck(); setCheck({ kind: 'recording' }) }}><Camera /></button>
          <button type="submit" className="round-button primary" aria-label={t.send} disabled><Send /></button>
        </form>
      </main>

      <aside className={sheet ? 'panel open' : 'panel'} aria-label={t.matrixTitle}>
        <HouseholdPanel t={t} view={panelView} language={language} schemes={schemes}
          onOpenScheme={setOpenScheme} onClose={() => setSheet(false)} />
      </aside>
      {sheet && <div className="scrim sheet-scrim" onClick={() => setSheet(false)} aria-hidden="true" />}

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
