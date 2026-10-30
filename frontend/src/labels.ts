// Names for people and documents, shared by the chat, the result cards and the household panel.
import type { Language, Member, SchemeResult, SessionView } from './api'
import type { Strings } from './i18n'

export function memberName(m: Member, language: Language, t: Strings): string {
  const name = language === 'en' ? m.name_en ?? m.name_mr : m.name_mr ?? m.name_en
  if (name) return name
  return m.on_ration_card ? t.cardMember.replace('{n}', m.member_id.replace(/^r/, '')) : t.personNotOnCard
}

export function docType(view: SessionView, docId: string): string | null {
  const ex = view.extractions?.find((e) => e.document_id === docId)
  const live = view.documents?.find((d) => d.id === docId)
  return ex?.doc_type ?? view.household?.documents[docId]?.doc_type ?? live?.doc_type ?? null
}

export function docOwner(view: SessionView, docId: string, language: Language, t: Strings): string | null {
  const type = docType(view, docId)
  const owner = view.household?.members.find((m) => Object.values(m.documents).some((ids) => ids.includes(docId)))
  if (owner && type !== 'ration_card') return memberName(owner, language, t)
  const ex = view.extractions?.find((e) => e.document_id === docId)
  const live = view.documents?.find((d) => d.id === docId)
  const f = (ex?.fields ?? {}) as Record<string, unknown>
  const en = (f.name_en as string | undefined) ?? live?.name_en ?? undefined
  const mr = (f.name_mr as string | undefined) ?? live?.name_mr ?? undefined
  return (language === 'en' ? en ?? mr : mr ?? en) ?? null
}

// 'Aadhaar card: Savita Aditya Bhosale' from the member it belongs to or the name read on it; else
// 'Aadhaar card 1/2' among the same type in `group`.
export function docLabel(view: SessionView, docId: string, group: string[], language: Language, t: Strings): string {
  const type = docType(view, docId)
  const typeName = (type && t.docTypes[type]) || t.document
  const name = docOwner(view, docId, language, t)
  if (name) return `${typeName}: ${name}`
  const same = group.filter((d) => docType(view, d) === type)
  return same.length > 1 ? `${typeName} ${same.indexOf(docId) + 1}/${same.length}` : typeName
}

// Each source once per scheme (several rules often cite the same page).
export function sources(r: SchemeResult): [string, string][] {
  const seen = new Map<string, string>()
  for (const x of r.rules) if (x.source_url && !seen.has(x.source_url)) seen.set(x.source_url, x.source)
  return [...seen.entries()]
}

export const OUTCOME_MARK: Record<SchemeResult['outcome'], string> = {
  eligible_on_documents: '✓', blocked_by_issues: '!', check_at_office: '?', not_eligible: '–',
}

// A box's reasons, with "a document could not be read" made specific: whose document, and which one, as the problems
// list says it. The backend adds one general line per problem type after the rule reasons, sorted by type, so the
// "unreadable" line is always the last one (agents/reasons.py). Saved checks keep their reasons as they were.
export function detailReasons(view: SessionView, r: SchemeResult, language: Language, t: Strings): string[] {
  const lines = r.display?.reasons ?? r.reasons
  const docs = (r.blocking_issues ?? [])
    .filter((i) => i.type === 'unreadable' && i.member_id === r.member_id).flatMap((i) => i.documents)
  if (!r.display || !docs.length || !lines.length) return lines
  const named = [...new Set(docs)].map((d) => {
    const type = docType(view, d)
    const document = (type && t.docTypes[type]) || t.document
    const who = docOwner(view, d, language, t)
    return (who ? t.unreadableNamed.replace('{name}', who) : t.unreadableDoc).replace('{document}', document)
  })
  return [...lines.slice(0, -1), ...named]
}
