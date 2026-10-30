import { useEffect, useState } from 'react'
import { ApiError, authStart, authVerify, getAuthConfig, type Language, type UserView } from '../api'
import { count } from '../counts'
import type { Strings } from '../i18n'
import LanguageMenu from './LanguageMenu'
import { Wordmark } from './Sidebar'

// Errors by HTTP status, in the family's language.
function authMessage(t: Strings, language: Language, e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 422) return t.errPhone
    if (e.status === 429) return t.errTooMany
    if (e.status === 401) return t.errWrong.replace('{tries}', count(language, 'tryLeft', e.attemptsLeft ?? 0))
    if (e.status === 410) return t.errExpired
    if (e.status === 503) return t.errUnavailable
  }
  return `${t.error}: ${e instanceof Error ? e.message : String(e)}`
}

// Phone, then the 6-digit code. Demo mode shows the code on screen; "Continue as guest" keeps today's flow.
export default function Login({ t, language, setLanguage, onLoggedIn, onGuest }: {
  t: Strings; language: Language; setLanguage: (l: Language) => void
  onLoggedIn: (token: string, user: UserView) => void; onGuest: () => void
}) {
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'phone' | 'code'>('phone')
  const [demoCode, setDemoCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'demo' | 'sms'>('demo')  // demo until the server says otherwise: no promise of an SMS

  useEffect(() => {
    getAuthConfig().then((c) => setMode(c.mode)).catch(() => { /* keep the demo wording */ })
  }, [])

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await authStart(phone)
      setDemoCode(r.demo_code)
      setCode('')
      setStep('code')
    } catch (e) {
      setError(authMessage(t, language, e))
    }
    setBusy(false)
  }

  const verify = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await authVerify(phone, code, language)
      onLoggedIn(r.token, r.user)
    } catch (e) {
      setError(authMessage(t, language, e))
      if (e instanceof ApiError && (e.status === 410 || e.status === 429)) setStep('phone')
      setBusy(false)
    }
  }

  const last4 = phone.replace(/\D/g, '').slice(-4)
  return (
    <div className="login-page">
      <header className="login-top">
        <Wordmark t={t} />
        <LanguageMenu t={t} language={language} onChange={setLanguage} />
      </header>
      <main className="login-card">
        <h1>{t.loginTitle}</h1>
        <p className="login-lead">{mode === 'demo' ? t.loginLeadDemo : t.loginLead}</p>
        {step === 'phone' ? (
          <form onSubmit={(e) => { e.preventDefault(); void start() }}>
            <label className="field">
              <span>{t.phoneLabel}</span>
              <span className="phone-input">
                <span className="prefix" aria-hidden="true">+91</span>
                <input type="tel" inputMode="numeric" autoComplete="tel-national" maxLength={16} value={phone}
                  onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210" />
              </span>
            </label>
            {mode === 'demo' && <p className="demo-notice">{t.demoNotice}</p>}
            <button type="submit" className="button primary big" disabled={busy || phone.replace(/\D/g, '').length < 10}>{t.getCode}</button>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); void verify() }}>
            {demoCode ? <p className="demo-code" role="status">{t.demoCode.replace('{code}', demoCode)}</p>
              : <p className="login-lead">{t.codeSent.replace('{last4}', last4)}</p>}
            <label className="field">
              <span>{t.codeLabel}</span>
              <input className="code-input" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
            </label>
            <button type="submit" className="button primary big" disabled={busy || code.length !== 6}>{t.logIn}</button>
            <button type="button" className="link-button" onClick={() => { setStep('phone'); setError(null) }}>{t.changeNumber}</button>
          </form>
        )}
        {error && <p className="alert" role="alert">{error}</p>}
        <p className="consent">{t.consent}</p>
        <div className="guest">
          <button type="button" className="button big" onClick={onGuest}>{t.guest}</button>
          <p className="guest-note">{t.guestNote}</p>
        </div>
        <p className="specimen-note">{t.specimen}</p>
      </main>
    </div>
  )
}
