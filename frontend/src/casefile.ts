// A stored check (the case file) in the shapes the live views already read.
import type { CheckFull, Language, SchemeResult, SessionView, Step, StepDisplay } from './api'

export function formatDateTime(iso: string, language: Language): string {
  return new Intl.DateTimeFormat(`${language}-IN`, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
    .format(new Date(iso))
}

export function formatDate(iso: string, language: Language): string {
  return new Intl.DateTimeFormat(`${language}-IN`, { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso))
}

// A stored check in the shape the live result cards and the household panel already read.
export function checkAsView(c: CheckFull): SessionView {
  const d = c.data
  const size = Math.max(-1, ...d.steps.map((s) => s.index)) + 1
  const answers = [...d.answers]
  const steps: Step[] = Array.from({ length: size }, () => {
    const a = answers.shift()
    return {
      kind: 'question', issue_ids: [], member_id: null, procedure_id: null, question: a?.question ?? null, options: [],
      answer: a?.answer ?? null, office: null, bring: [], fee: null, time_limit: null, cautions: [], declaration: null,
      facts: [], visit: null, voice: '',
    }
  })
  const speech: NonNullable<SessionView['speech']> = steps.map((_, i) => ({ index: i, kind: 'question', text: '', speech: '', display: null }))
  for (const s of d.steps) {
    steps[s.index] = { ...steps[s.index], kind: s.kind, question: null, answer: null, member_id: s.member_id, visit: s.visit, voice: s.voice }
    const display: StepDisplay = { office: s.office, bring: s.bring, fee: s.fee, time_limit: s.time_limit }
    speech[s.index] = { index: s.index, kind: s.kind, text: s.voice, speech: s.speech, display }
  }
  for (const a of answers) steps.push({ ...steps[0], kind: 'question', question: a.question, answer: a.answer })
  const results: SchemeResult[] = d.outcomes.map((o) => ({
    scheme_id: o.scheme_id, scheme_name: o.scheme_id, member_id: o.member_id, outcome: o.outcome, reasons: o.reasons,
    rules: [], warnings: o.warnings, display: { reasons: o.reasons, warnings: o.warnings },
  }))
  return {
    id: c.id, language: c.language, sample: false, status: 'done', error: null, stage: null, stages: [], question: null,
    elapsed_s: 0, found: null, extractions: null, recapture: null, waiting: null,
    issues: d.problems.filter((p) => !p.waiting).map((p, i) => ({
      id: `p${i}`, type: p.type, severity: 'blocker', member_id: p.member_id, member_name: p.member_name,
      member_name_mr: p.member_name_mr, documents: {}, document_type: null,
    })),
    household: { members: d.members.map((m) => ({ ...m, documents: {} })), documents: {}, issues: [] },
    results, plan: { steps, source: 'stored' }, speech,
  }
}
