import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { getSchemes, getSession, startSample, startUpload, type CatalogScheme, type Language, type SessionView } from './api'
import { stop } from './audio'
import { STRINGS } from './i18n'
import Chat, { type Answered, type Check } from './ui/Chat'
import HouseholdPanel from './ui/HouseholdPanel'
import { Camera, Family, Menu, Mic, Send } from './ui/Icons'
import LanguageMenu from './ui/LanguageMenu'
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

export default function App() {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem('kaagaz.lang') as Language) || 'mr')
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

  const onAnswered = useCallback((label: string) => {
    if (view?.question) setAnswered((a) => [...a, { question: view.question!.screen, member: view.question!.member, answer: label }])
    refresh()
  }, [view, refresh])
  const voice = useVoiceAnswer(t, sessionId, view?.status === 'waiting' ? view.question : null, onAnswered)

  // Follow the conversation as it grows (not on every poll: only when something new appears).
  const signature = [check.kind, view?.status, view?.stage, view?.question?.question_id, answered.length,
    view?.recapture?.mode, view?.plan?.steps.length].join('|')
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [signature])

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
  const onSample = () => void begin(true, () => startSample(language))
  const onRecorded = (blob: Blob) => void begin(false, () => startUpload(blob, language,
    (percent) => setCheck((c) => (c.kind === 'uploading' ? { ...c, percent } : c))))
  const newCheck = () => {
    stop()
    setCheck({ kind: 'idle' })
    setAnswered([])
    setStartError(null)
    setDrawer(false)
    setSheet(false)
  }

  const busy = check.kind === 'recording' || check.kind === 'uploading' || view?.status === 'running' || view?.status === 'waiting'
  const scheme = schemes.find((s) => s.id === openScheme)
  const members = view?.household?.members.length ?? 0

  return (
    <div className="shell">
      <aside className={drawer ? 'side open' : 'side'}>
        <Sidebar t={t} schemes={schemes} onNewCheck={newCheck} onOpenScheme={(id) => { setOpenScheme(id); setDrawer(false) }}
          onClose={() => setDrawer(false)} />
      </aside>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}

      <main className="center">
        <header className="topbar">
          <button type="button" className="icon-button only-narrow" aria-label={t.menu} onClick={() => setDrawer(true)}><Menu /></button>
          <div className="only-narrow"><Wordmark t={t} /></div>
          <LanguageMenu t={t} language={language} onChange={setLanguage} />
        </header>

        <div className="conversation" ref={scroller}>
          <div className="conversation-inner">
            <Chat t={t} language={language} schemes={schemes} check={check} view={view} error={startError ?? error} answered={answered}
              voice={voice} onRecord={() => setCheck({ kind: 'recording' })} onSample={onSample} onRecorded={onRecorded}
              onCancelRecord={() => setCheck({ kind: 'idle' })} onAnswered={onAnswered} onReplanned={refresh}
              onNewCheck={newCheck} />
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
        <HouseholdPanel t={t} view={view} language={language} schemes={schemes}
          onOpenScheme={setOpenScheme} onClose={() => setSheet(false)} />
      </aside>
      {sheet && <div className="scrim sheet-scrim" onClick={() => setSheet(false)} aria-hidden="true" />}

      {scheme && <SchemeCard key={scheme.id} t={t} scheme={scheme} onClose={() => setOpenScheme(null)} />}
    </div>
  )
}
