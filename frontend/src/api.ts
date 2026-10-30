// Client for the Kaagaz backend (backend/app/api/routes.py).

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
  status: 'running' | 'waiting' | 'done' | 'error'
  error: string | null
  stage: Stage | null
  stages: { stage: Stage; done: boolean; seconds: number | null }[]
  question: Question | null
  elapsed_s: number
  found: { id: string; frames: number[]; fully_visible: boolean }[] | null
  documents?: LiveDocument[] | null // found so far, while the finder runs (and after); crops at cropUrl()
  extractions: Extraction[] | null
  issues: PlannerIssue[] | null // the problems the plan is for
  waiting: WaitingIssue[] | null
  recapture: { mode: 'none' | 'close_ups' | 'sweep_again' | 'no_documents'; documents: string[] } | null
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

export interface CatalogScheme { id: string; name: string; rules: CatalogLine[]; other_proof: CatalogLine[] }

export interface AnswerReply { action: 'answered' | 'ask_again' | 'show_buttons'; option: number | null; say: string | null; heard?: string | null }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export async function startSample(language: Language): Promise<string> {
  const res = await fetch(`${API_URL}/sessions/sample`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language }),
  })
  return (await json<{ id: string }>(res)).id
}

// XMLHttpRequest rather than fetch: fetch has no upload progress, and a 20 MB sweep on slow mobile data takes a
// while. `onProgress` gets 0-100 while sending; the server then normalizes the video before answering.
export function startUpload(video: Blob, language: Language, onProgress?: (percent: number) => void): Promise<string> {
  const form = new FormData()
  form.append('language', language)
  form.append('video', video, video.type.includes('mp4') ? 'sweep.mp4' : 'sweep.webm')
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_URL}/sessions`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100)) }
    xhr.upload.onload = () => onProgress?.(100)
    xhr.onload = () => {
      const body = xhr.response as { id?: string; detail?: string } | null
      if (xhr.status >= 200 && xhr.status < 300 && body?.id) resolve(body.id)
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
