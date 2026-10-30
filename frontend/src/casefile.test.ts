// The comparison card's lines (the same functions ComparisonCard and ProblemList render with), in en/hi/mr.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Comparison } from './api.ts'
import { changeLine, problemLine } from './casefile.ts'
import { STRINGS } from './i18n.ts'

const comparison: Comparison = {
  previous_created: '2026-10-30T10:00:00Z',
  fixed: [{ type: 'name_mismatch', member_id: 'r2', member_name: 'Savita Aditya Bhosale', member_name_mr: 'सविता आदित्य भोसले',
    document_types: ['identity_card'], waiting: false }],
  new: [{ type: 'unreadable', member_id: null, member_name: 'Lata Aditya Bhosale', member_name_mr: 'लता आदित्य भोसले',
    document_types: ['caste_certificate'], waiting: false }],
  still_open: [],
  outcomes_changed: [{ member_name: 'Savita Aditya Bhosale', member_name_mr: 'सविता आदित्य भोसले', scheme_id: 'ladki_bahin',
    before: 'blocked_by_issues', after: 'eligible_on_documents' }],
}
const NAMES = { ladki_bahin: 'Ladki Bahin' }

const EXPECTED = {
  en: { fixed: ['Name spelled differently', 'Savita Aditya Bhosale · Aadhaar card'],
    new: ['Could not read', 'Lata Aditya Bhosale · Caste certificate'],
    change: 'Ladki Bahin: now eligible on these documents' },
  hi: { fixed: ['नाम की स्पेलिंग अलग', 'सविता आदित्य भोसले · आधार कार्ड'],
    new: ['पढ़ा नहीं जा सका', 'लता आदित्य भोसले · जाति प्रमाण पत्र'],
    change: 'Ladki Bahin: अब इन दस्तावेज़ों पर पात्र' },
  mr: { fixed: ['नावाची स्पेलिंग वेगळी', 'सविता आदित्य भोसले · आधार कार्ड'],
    new: ['वाचता आले नाही', 'लता आदित्य भोसले · जातीचा दाखला'],
    change: 'Ladki Bahin: आता या कागदपत्रांनुसार पात्र' },
} as const

for (const language of ['en', 'hi', 'mr'] as const) {
  test(`a fixed and a new problem both render, with names, in ${language}`, () => {
    const t = STRINGS[language]
    const fixed = problemLine(t, language, comparison.fixed[0])
    const added = problemLine(t, language, comparison.new[0])
    assert.deepEqual([fixed.title, fixed.detail], EXPECTED[language].fixed)
    assert.deepEqual([added.title, added.detail], EXPECTED[language].new)
    const change = changeLine(t, language, comparison.outcomes_changed[0], NAMES)
    assert.equal(change.title, EXPECTED[language].change)
    assert.equal(change.detail, language === 'en' ? 'Savita Aditya Bhosale' : 'सविता आदित्य भोसले')
  })
}

test('a problem with nobody known shows the document only', () => {
  const line = problemLine(STRINGS.en, 'en', { ...comparison.new[0], member_name: null, member_name_mr: null })
  assert.equal(line.detail, 'Caste certificate')
})
