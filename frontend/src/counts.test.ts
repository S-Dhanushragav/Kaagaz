// Run with `npm test` (Node's built-in test runner; no test framework needed).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { count, type Noun } from './counts.ts'

const NOUNS: Noun[] = ['step', 'stepOpen', 'problemFound', 'visitOpen', 'person', 'secondsTaken', 'tryLeft']

test('English: singular for 1, plural for 2', () => {
  assert.equal(count('en', 'step', 1), '1 step')
  assert.equal(count('en', 'step', 2), '2 steps')
  assert.equal(count('en', 'stepOpen', 1), '1 step open')
  assert.equal(count('en', 'stepOpen', 2), '2 steps open')
  assert.equal(count('en', 'problemFound', 1), '1 problem')
  assert.equal(count('en', 'problemFound', 2), '2 problems')
  assert.equal(count('en', 'visitOpen', 1), '1 office visit is still open')
  assert.equal(count('en', 'visitOpen', 2), '2 office visits are still open')
  assert.equal(count('en', 'person', 1), '1 person')
  assert.equal(count('en', 'person', 2), '2 people')
  assert.equal(count('en', 'secondsTaken', 1), '1 second')
  assert.equal(count('en', 'tryLeft', 1), '1 try left')
  assert.equal(count('en', 'tryLeft', 2), '2 tries left')
})

test('Hindi: singular for 1, plural for 2', () => {
  assert.equal(count('hi', 'problemFound', 1), '1 समस्या मिली थी')
  assert.equal(count('hi', 'problemFound', 2), '2 समस्याएँ मिली थीं')
  assert.equal(count('hi', 'person', 1), '1 व्यक्ति')
  assert.equal(count('hi', 'person', 2), '2 लोग')
  assert.equal(count('hi', 'tryLeft', 1), '1 कोशिश बाकी')
  assert.equal(count('hi', 'tryLeft', 2), '2 कोशिशें बाकी')
  assert.equal(count('hi', 'step', 2), '2 काम')
})

test('Marathi: singular for 1, plural for 2', () => {
  assert.equal(count('mr', 'step', 1), '1 काम')
  assert.equal(count('mr', 'step', 2), '2 कामे')
  assert.equal(count('mr', 'stepOpen', 1), '1 काम बाकी')
  assert.equal(count('mr', 'stepOpen', 2), '2 कामे बाकी')
  assert.equal(count('mr', 'problemFound', 1), '1 अडचण आढळली')
  assert.equal(count('mr', 'problemFound', 2), '2 अडचणी आढळल्या')
  assert.equal(count('mr', 'visitOpen', 1), '1 कार्यालय भेट अजून बाकी आहे')
  assert.equal(count('mr', 'visitOpen', 2), '2 कार्यालय भेटी अजून बाकी आहेत')
  assert.equal(count('mr', 'secondsTaken', 2), '2 सेकंदांत')
})

test('every noun has both forms in every language, and they differ where the language inflects', () => {
  for (const language of ['en', 'hi', 'mr'] as const) {
    for (const noun of NOUNS) {
      assert.match(count(language, noun, 1), /^.*1.*$/)
      assert.match(count(language, noun, 2), /2/)
      assert.doesNotMatch(count(language, noun, 2), /\{n\}/)
    }
  }
  for (const noun of NOUNS) assert.notEqual(count('en', noun, 1).replace('1', ''), count('en', noun, 2).replace('2', ''))
})
