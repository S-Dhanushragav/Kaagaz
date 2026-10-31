// Client for the Kaagaz backend (backend/app/api/routes.py).
import { photosSent } from './photos'

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8000'

export type Language = 'mr' | 'hi' | 'en'
export type Stage = 'find_documents' | 'read_documents' | 'build_household' | 'check_rules' | 'plan_fixes' | 'speak'

export interface Question {
  question_id: string
  issue_type: string
  severity: string // 'blocker' | 'confirm' | ...
  kind: 'which_is_correct' | 'compare'
  member: string | null
  screen: string
  speech: string
  documents: string
  options: string[]
  shown: string[]
  english_only: boolean
  values: { document_type: string; value: string }[]
}

export interface Fact { fact: string; value: string; status: 'verified' | 'unverified'; source_url: string | null }

export interface Step {
  kind: 'question' | 'fix' | 'ask_at_office'
  issue_ids: string[]
  member_id: string | null
  procedure_id: string | null
  question: string | null
  options: string[]
  answer: string | null
  office: string | null
  bring: string[]
  fee: string | null
  time_limit: string | null
  cautions: string[]
  declaration: string | null
  facts: Fact[]
  visit: number | null
  voice: string
}

export interface Member {
  member_id: string
  on_ration_card: boolean
  name_mr: string | null
  name_en: string | null
  relation_en: string | null
  age: number | null
  documents: Record<string, string[]>
}

export interface Issue {
  type: string
  severity: string
  member_id: string | null
  documents: string[]
  message: string
}

export interface RuleResult {
  rule_id: string
  outcome: string
  reason: string
  status: string
  source: string
  source_url: string | null
}

export interface SchemeResult {
  scheme_id: string
  scheme_name: string
  member_id: string
  outcome: 'not_eligible' | 'blocked_by_issues' | 'check_at_office' | 'eligible_on_documents'
  reasons: string[]
  rules: RuleResult[]
  warnings: string[]
  display?: { reasons: string[]; warnings: string[] } // in the family's language (backend templates)
  blocking_issues?: Issue[] // the member's problems that block this scheme (live checks; not stored)
}

export interface Shown { text: string; verified: boolean }
export interface StepDisplay { office: Shown | null; bring: Shown[]; fee: Shown | null; time_limit: Shown | null }

export interface Extraction {
  document_id: string
  doc_type: string | null
  unreadable: boolean
  fields: Record<string, unknown> | null
}

// An issue as the fix planner saw it (also the shape of a waiting issue).
export interface PlannerIssue {
  id: string
  type: string
  severity: string
  member_id: string | null
  member_name: string | null
  member_name_mr: string | null
  documents: Record<string, string> // document id -> document type
  document_type: string | null // for a missing document: which one
}

export interface WaitingIssue { id: string; type: string; member_id: string | null; member_name: string | null; member_name_mr: string | null; documents: Record<string, string> }

// A document the finder has handed over, with what is known about it so far (type and name once read).
export interface LiveDocument { id: string; doc_type: string | null; name_en: string | null; name_mr: string | null; read: boolean }

export interface SessionView {
  id: string
  language: Language
  sample: boolean
  kind?: 'video' | 'photos' | 'sample'
  status: 'running' | 'waiting' | 'done' | 'error'
  error: string | null
  stage: Stage | null
  stages: { stage: Stage; done: boolean; seconds: number | null }[]
  question: Question | null
  elapsed_s: number
  found: { id: string; frames: number[]; fully_visible: boolean }[] | null
  documents?: LiveDocument[] | null // found so far, while the finder runs (and after); crops at cropUrl()
  check_id?: string | null // logged in: the saved check
  recheck_of?: string | null // "Check again": the check this one re-checks
  extractions: Extraction[] | null
  issues: PlannerIssue[] | null // the problems the plan is for
  waiting: WaitingIssue[] | null
  // close_ups: some documents need a clearer photo (the rest goes ahead); hold: more than half do, so the matrix and
  // plan wait for photos; no_documents: nothing was read. unidentified: items that looked like documents but were
  // not read as any type; read: documents read as a known type (clearly or not).
  recapture: { mode: 'none' | 'close_ups' | 'hold' | 'no_documents'; documents: string[]; unidentified?: string[]; read?: number } | null
  household: {
    members: Member[]
    documents: Record<string, { document_id: string; doc_type: string | null; unreadable: boolean }>
    issues: Issue[]
  } | null
  results: SchemeResult[] | null
  plan: { steps: Step[]; source: string } | null
  speech: { index: number; kind: string; text: string; speech: string; display: StepDisplay | null }[] | null
}

export interface CatalogLine {
  rule_id: string
  check: string
  text: string
  status: 'verified' | 'conflict' | 'unverified'
  sources: { source: string; url: string | null }[]
  last_checked: string
}

export interface CatalogScheme {
  id: string
  name: string // full name
  short: string // short name (the household matrix)
  benefit: { text: string; status: CatalogLine['status']; sources: CatalogLine['sources']; last_checked: string }
  rules: CatalogLine[]
  other_proof: CatalogLine[]
}

export interface AnswerReply { action: 'answered' | 'ask_again' | 'show_buttons'; option: number | null; say: string | null; heard?: string | null }

// An HTTP error with its status (the app words most errors itself, by status, in the family's language).
export class ApiError extends Error {
  status: number
  attemptsLeft: number | null
  code: string | null // e.g. 'silent' for a spoken question nothing was heard in
  constructor(status: number, message: string, attemptsLeft: number | null = null, code: string | null = null) {
    super(message)
    this.status = status
    this.attemptsLeft = attemptsLeft
    this.code = code
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = res.statusText
    let attemptsLeft: number | null = null
    let code: string | null = null
    try {
      const detail = (await res.json()).detail
      if (typeof detail === 'string') message = detail
      else if (detail?.message) { message = detail.message; attemptsLeft = detail.attempts_left ?? null; code = detail.code ?? null }
    } catch { /* not JSON */ }
    throw new ApiError(res.status, message, attemptsLeft, code)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ---------- login token: sent as a Bearer header (the app and the API are on different domains) ----------

let token: string | null = localStorage.getItem('kaagaz.token')

export function setToken(t: string | null): void {
  token = t
  if (t) localStorage.setItem('kaagaz.token', t)
  else localStorage.removeItem('kaagaz.token')
}

export const hasToken = (): boolean => token !== null

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

// A started check: its id, and the guest secret that lets this browser (only) save it after logging in.
export interface Started { id: string; guestSecret: string }

export async function startSample(language: Language, recheckOf: string | null = null): Promise<Started> {
  const res = await fetch(`${API_URL}/sessions/sample`, {
    method: 'POST', headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ language, recheck_of: recheckOf }),
  })
  const body = await json<{ id: string; guest_secret: string }>(res)
  return { id: body.id, guestSecret: body.guest_secret }
}

// XMLHttpRequest rather than fetch: fetch has no upload progress, and a 20 MB sweep on slow mobile data takes a
// while. `onProgress` gets 0-100 while sending; the server then normalizes the video before answering.
export function startUpload(video: Blob, language: Language, onProgress?: (percent: number) => void,
  recheckOf: string | null = null): Promise<Started> {
  const form = new FormData()
  form.append('language', language)
  if (recheckOf) form.append('recheck_of', recheckOf)
  form.append('video', video, video.type.includes('mp4') ? 'sweep.mp4' : 'sweep.webm')
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_URL}/sessions`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100)) }
    xhr.upload.onload = () => onProgress?.(100)
    xhr.onload = () => {
      const body = xhr.response as { id?: string; guest_secret?: string; detail?: string } | null
      if (xhr.status >= 200 && xhr.status < 300 && body?.id) resolve({ id: body.id, guestSecret: body.guest_secret ?? '' })
      else reject(new Error(body?.detail ?? `HTTP ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.ontimeout = () => reject(new Error('timed out'))
    xhr.send(form)
  })
}

// Photo mode: up to 12 photos (already resized and stripped of EXIF in the browser, see photos.ts) in one request.
// `onProgress` gets how many photos have been sent so far (by bytes), for "Uploading 3 of 5".
export function startPhotos(photos: Blob[], language: Language, onProgress?: (sent: number, total: number) => void,
  recheckOf: string | null = null): Promise<Started> {
  const form = new FormData()
  form.append('language', language)
  if (recheckOf) form.append('recheck_of', recheckOf)
  photos.forEach((p, i) => form.append('photos', p, `photo${i + 1}.jpg`))
  const sizes = photos.map((p) => p.size)
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_URL}/sessions/photos`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(photosSent(e.loaded / e.total, sizes), photos.length) }
    xhr.upload.onload = () => onProgress?.(photos.length, photos.length)
    xhr.onload = () => {
      const body = xhr.response as { id?: string; guest_secret?: string; detail?: string } | null
      if (xhr.status >= 200 && xhr.status < 300 && body?.id) resolve({ id: body.id, guestSecret: body.guest_secret ?? '' })
      else reject(new Error(body?.detail ?? `HTTP ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.ontimeout = () => reject(new Error('timed out'))
    xhr.send(form)
  })
}

export async function getSession(id: string): Promise<SessionView> {
  return json<SessionView>(await fetch(`${API_URL}/sessions/${id}`))
}

export async function answerOption(id: string, questionId: string, option: number): Promise<AnswerReply> {
  const res = await fetch(`${API_URL}/sessions/${id}/answer`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question_id: questionId, option }),
  })
  return json<AnswerReply>(res)
}

export async function answerAudio(id: string, questionId: string, wav: Blob): Promise<AnswerReply> {
  const form = new FormData()
  form.append('question_id', questionId)
  form.append('audio', wav, 'answer.wav')
  return json<AnswerReply>(await fetch(`${API_URL}/sessions/${id}/answer`, { method: 'POST', body: form }))
}

export async function sendCloseup(id: string, documentId: string, photo: Blob | null): Promise<{ clear: boolean; missing: string[] }> {
  const form = new FormData()
  form.append('document_id', documentId)
  if (photo) form.append('photo', photo, 'closeup.jpg')
  else form.append('sample', 'true')
  return json(await fetch(`${API_URL}/sessions/${id}/closeup`, { method: 'POST', body: form }))
}

export async function getSchemes(language: Language): Promise<CatalogScheme[]> {
  return json<CatalogScheme[]>(await fetch(`${API_URL}/schemes?lang=${language}`))
}

export const audioUrl = (id: string, key: string): string => `${API_URL}/sessions/${id}/audio/${key}`
export const cropUrl = (id: string, documentId: string, version = 0): string =>
  `${API_URL}/sessions/${id}/crops/${encodeURIComponent(documentId)}?v=${version}`

// Thumbs up/down on the plan ('plan') or one answer ('answer:<id>'), stored anonymously.
export async function sendFeedback(sessionId: string, target: string, value: 'up' | 'down', comment?: string): Promise<void> {
  const res = await fetch(`${API_URL}/feedback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, target, value, comment: comment || null }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

// ---------- login and the case file ----------

export interface UserView { id: string; phone_last4: string; language: Language; created: string }

export async function authStart(phone: string): Promise<{ sent: boolean; expires_in: number; demo_code: string | null }> {
  return json(await fetch(`${API_URL}/auth/start`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ phone }),
  }))
}

export async function authVerify(phone: string, code: string, language: Language): Promise<{ token: string; user: UserView }> {
  return json(await fetch(`${API_URL}/auth/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ phone, code, language }),
  }))
}

export async function getMe(): Promise<UserView> {
  return json(await fetch(`${API_URL}/me`, { headers: headers() }))
}

export async function setMyLanguage(language: Language): Promise<UserView> {
  return json(await fetch(`${API_URL}/me`, {
    method: 'PATCH', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ language }),
  }))
}

export async function deleteMe(): Promise<void> {
  return json(await fetch(`${API_URL}/me`, { method: 'DELETE', headers: headers() }))
}

export interface StoredFact { text: string; verified: boolean }
export interface StoredMember { member_id: string; name_mr: string | null; name_en: string | null; relation_en: string | null; age: number | null; on_ration_card: boolean }
export interface StoredProblem { type: string; member_id: string | null; member_name: string | null; member_name_mr: string | null; document_types: string[]; waiting: boolean }
export interface StoredOutcome { member_id: string; scheme_id: string; outcome: SchemeResult['outcome']; reasons: string[]; warnings: string[] }
export interface StoredStep {
  index: number; kind: 'fix' | 'ask_at_office'; visit: number | null; office: StoredFact | null; voice: string; speech: string
  bring: StoredFact[]; fee: StoredFact | null; time_limit: StoredFact | null; member_id: string | null
}
export interface CheckData {
  members: StoredMember[]; documents: string[]; problems: StoredProblem[]; outcomes: StoredOutcome[]
  steps: StoredStep[]; answers: { question: string; answer: string }[]
}
export interface CheckSummary {
  id: string; created: string; language: Language; previous_id: string | null
  head: { name_en: string | null; name_mr: string | null } | null
  problems: number; steps: number; open_steps: number; open_visits: number
}
export interface Comparison {
  previous_created: string; fixed: StoredProblem[]; still_open: StoredProblem[]; new: StoredProblem[]
  outcomes_changed: { member_name: string | null; member_name_mr: string | null; scheme_id: string; before: string; after: SchemeResult['outcome'] }[]
}
export interface CheckFull extends CheckSummary { data: CheckData; steps_done: Record<string, boolean>; comparison: Comparison | null }

export async function myChecks(): Promise<CheckSummary[]> {
  return json(await fetch(`${API_URL}/me/checks`, { headers: headers() }))
}

export async function myCheck(id: string): Promise<CheckFull> {
  return json(await fetch(`${API_URL}/me/checks/${id}`, { headers: headers() }))
}

export async function tickStep(id: string, step: number, done: boolean): Promise<CheckSummary> {
  return json(await fetch(`${API_URL}/me/checks/${id}/steps/${step}`, {
    method: 'PATCH', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ done }),
  }))
}

export const storedAudioUrl = (id: string, step: number): string => `${API_URL}/me/checks/${id}/audio/${step}`

// <audio> cannot send the Bearer header: case-file audio is fetched here and played from a blob URL.
const blobs = new Map<string, string>()
export async function playableUrl(url: string): Promise<string> {
  if (!url.startsWith(`${API_URL}/me/`)) return url
  const cached = blobs.get(url)
  if (cached) return cached
  const res = await fetch(url, { headers: headers() })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const blobUrl = URL.createObjectURL(await res.blob())
  blobs.set(url, blobUrl)
  return blobUrl
}

// After logging in from the "Save this check" card: keep that guest check (while the session is still in memory).
export async function claimSession(sessionId: string, guestSecret: string): Promise<{ check_id: string | null }> {
  return json(await fetch(`${API_URL}/sessions/${sessionId}/claim`, {
    method: 'POST', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ guest_secret: guestSecret }),
  }))
}

// Demo mode sends no SMS (the code is shown on screen): the login screen says so.
export async function getAuthConfig(): Promise<{ mode: 'demo' | 'sms' }> {
  return json(await fetch(`${API_URL}/auth/config`))
}

// ---------- Ask Kaagaz ----------

// An "Add a photo" button the answer offers: closeup opens Take a photo / Upload for a document waiting for a clearer
// photo (live checks); add_photos starts adding photos (a missing document, or a saved check).
export interface AskChip {
  id: string; kind: 'closeup' | 'add_photos'; document_id: string | null; document_type: string | null
  member_id: string | null; label: string
}
export interface AskReply {
  id: string // for the answer's audio
  kind: 'answer' | 'out_of_scope' | 'id_number' | 'other_language' | 'not_sure' | 'unavailable'
  text: string
  note: string | null // "check it at the office"
  sources: { label: string; url: string }[]
  chips: AskChip[]
}
// The family the question is about: a finished live check, a saved check (logged in), or none (schemes only).
export interface AskContext { sessionId?: string; checkId?: string }

// `voiceTicket`: the question was spoken and already counted when it was transcribed.
export async function askKaagaz(question: string, language: Language, context: AskContext,
  voiceTicket: string | null = null): Promise<AskReply> {
  return json(await fetch(`${API_URL}/ask`, {
    method: 'POST', headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ question, language, session_id: context.sessionId ?? null, check_id: context.checkId ?? null,
      voice_ticket: voiceTicket }),
  }))
}

export interface Transcribed { text: string; voice_ticket: string; timings: { audio_s: number; convert_s: number; transcribe_s: number } }

// A spoken question (WebM/Opus or MP4/AAC as recorded): the backend converts and transcribes it; nothing is kept.
export async function transcribeQuestion(audio: Blob, language: Language, context: AskContext): Promise<Transcribed> {
  const form = new FormData()
  form.append('audio', audio, audio.type.includes('mp4') ? 'question.mp4' : 'question.webm')
  form.append('language', language)
  if (context.sessionId) form.append('session_id', context.sessionId)
  if (context.checkId) form.append('check_id', context.checkId)
  return json(await fetch(`${API_URL}/ask/transcribe`, { method: 'POST', headers: headers(), body: form }))
}

export async function askSuggestions(language: Language, context: AskContext): Promise<string[]> {
  const q = new URLSearchParams({ language })
  if (context.sessionId) q.set('session_id', context.sessionId)
  if (context.checkId) q.set('check_id', context.checkId)
  return json(await fetch(`${API_URL}/ask/suggestions?${q}`, { headers: headers() }))
}

export const askAudioUrl = (id: string): string => `${API_URL}/ask/audio/${encodeURIComponent(id)}`
