// The cell detail names whose document could not be read, in en/hi/mr (the same helper SchemesCard renders with).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { SchemeResult, SessionView } from './api.ts'
import { STRINGS } from './i18n.ts'
import { detailReasons } from './labels.ts'

const view = {
  extractions: [{ document_id: 'd2', doc_type: 'identity_card', unreadable: true, fields: { name_en: 'Savita Aditya Bhosale', name_mr: 'सविता आदित्य भोसले' } }],
  household: {
    members: [{ member_id: 'r2', on_ration_card: true, name_mr: 'सविता आदित्य भोसले', name_en: 'Savita Aditya Bhosale',
      relation_en: null, age: 46, documents: { identity_card: ['d2'] } }],
    documents: { d2: { document_id: 'd2', doc_type: 'identity_card', unreadable: true } }, issues: [],
  },
} as unknown as SessionView

const result = (reasons: string[]): SchemeResult => ({
  scheme_id: 'ladki_bahin', scheme_name: 'Ladki Bahin', member_id: 'r2', outcome: 'blocked_by_issues', reasons: [], rules: [],
  warnings: [], display: { reasons, warnings: [] },
  blocking_issues: [{ type: 'unreadable', severity: 'blocker', member_id: 'r2', documents: ['d2'], message: '' }],
})

const EXPECTED = {
  en: "Savita Aditya Bhosale's Aadhaar card could not be read: take a clearer photo first.",
  hi: 'सविता आदित्य भोसले का आधार कार्ड पढ़ा नहीं जा सका: पहले साफ़ फ़ोटो लें।',
  mr: 'सविता आदित्य भोसले: आधार कार्ड: वाचता आले नाही. आधी स्पष्ट फोटो घ्या.',
}

for (const language of ['en', 'hi', 'mr'] as const) {
  test(`the unreadable line names the person and the document in ${language}`, () => {
    const lines = detailReasons(view, result(['Is a woman, as required.', 'A document could not be read: take a clearer photo first.']),
      language, STRINGS[language])
    assert.deepEqual(lines, ['Is a woman, as required.', EXPECTED[language]])
  })
}

test('results without an unreadable problem keep their reasons as they are', () => {
  const plain = { ...result(['Age 48 is under the minimum age of 65.']), blocking_issues: [] }
  assert.deepEqual(detailReasons(view, plain, 'en', STRINGS.en), ['Age 48 is under the minimum age of 65.'])
})
