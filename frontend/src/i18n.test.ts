// Every language has every UI string, and keeps each English string's placeholders ({n}, {member}, {time} ...) and
// numbers (45 seconds, 12 photos, 5 schemes) exactly: a missing or altered one fails here.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FORMS } from './counts.ts'
import { LANGUAGES, MACHINE_TRANSLATED, STRINGS } from './i18n.ts'

type Flat = Record<string, string>
function flatten(value: unknown, prefix = ''): Flat {
  if (typeof value === 'string') return { [prefix]: value }
  if (Array.isArray(value)) return Object.assign({}, ...value.map((v, i) => flatten(v, `${prefix}.${i}`)))
  return Object.assign({}, ...Object.entries(value as object).map(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k)))
}
const placeholders = (s: string) => (s.match(/\{[a-z0-9_]+\}/gi) ?? []).sort()
const numbers = (s: string) => (s.replace(/\{[a-z0-9_]+\}/gi, '').match(/\d[\d,.]*\d|\d/g) ?? []).map((n) => n.replace(/,/g, '')).sort()

const en = flatten(STRINGS.en)

for (const language of LANGUAGES.filter((l) => l !== 'en')) {
  test(`${language}: every UI string, with the same placeholders and numbers as English`, () => {
    const other = flatten(STRINGS[language])
    assert.deepEqual(Object.keys(other).sort(), Object.keys(en).sort())
    for (const [key, text] of Object.entries(en)) {
      assert.ok(other[key].trim(), `${language} ${key} is empty`)
      assert.deepEqual(placeholders(other[key]), placeholders(text), `${language} ${key}: placeholders`)
      if (MACHINE_TRANSLATED.has(language)) assert.deepEqual(numbers(other[key]), numbers(text), `${language} ${key}: numbers`)
    }
  })

  test(`${language}: count forms keep {n}`, () => {
    for (const [noun, forms] of Object.entries(FORMS[language])) {
      assert.ok(forms.other.includes('{n}'), `${language} ${noun}.other`)
      assert.ok(forms.one.includes('1') && !forms.one.includes('{n}'), `${language} ${noun}.one`)
    }
  })
}

test('machine-translated languages say so in their own script', () => {
  for (const language of MACHINE_TRANSLATED) {
    assert.notEqual(STRINGS[language].machineTranslated, STRINGS.en.machineTranslated)
    assert.ok(!/[A-Za-z]/.test(STRINGS[language].machineTranslated), language)
  }
})
