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
  for (const language of ['en', 'hi', 'mr', 'ta', 'te', 'kn'] as const) {
    for (const noun of NOUNS) {
      assert.match(count(language, noun, 1), /^.*1.*$/)
      assert.match(count(language, noun, 2), /2/)
      assert.doesNotMatch(count(language, noun, 2), /\{n\}/)
    }
  }
  for (const noun of NOUNS) assert.notEqual(count('en', noun, 1).replace('1', ''), count('en', noun, 2).replace('2', ''))
})

// Tamil, Telugu and Kannada (machine-translated, src/locales): the singular for exactly 1, the plural for 2
test('Tamil: singular for 1, plural for 2', () => {
  assert.equal(count('ta', 'person', 1), '1 நபர்')
  assert.equal(count('ta', 'person', 2), '2 நபர்கள்')
  assert.equal(count('ta', 'problemFound', 1), '1 சிக்கல்')
  assert.equal(count('ta', 'problemFound', 2), '2 சிக்கல்கள்')
  assert.equal(count('ta', 'stepOpen', 1), '1 படி மீதம் உள்ளது')
  assert.equal(count('ta', 'stepOpen', 2), '2 படிகள் மீதம் உள்ளன')
  assert.equal(count('ta', 'tryLeft', 1), '1 முயற்சி மீதம் உள்ளது')
  assert.equal(count('ta', 'tryLeft', 2), '2 முயற்சிகள் மீதம் உள்ளன')
})

test('Telugu: singular for 1, plural for 2', () => {
  assert.equal(count('te', 'person', 1), '1 వ్యక్తి')
  assert.equal(count('te', 'person', 2), '2 మంది')
  assert.equal(count('te', 'problemFound', 1), '1 సమస్య')
  assert.equal(count('te', 'problemFound', 2), '2 సమస్యలు')
  assert.equal(count('te', 'visitOpen', 1), '1 కార్యాలయ సందర్శన ఇంకా మిగిలి ఉంది')
  assert.equal(count('te', 'visitOpen', 2), '2 కార్యాలయ సందర్శనలు ఇంకా మిగిలి ఉన్నాయి')
  assert.equal(count('te', 'tryLeft', 1), '1 ప్రయత్నం మిగిలి ఉంది')
  assert.equal(count('te', 'tryLeft', 2), '2 ప్రయత్నాలు మిగిలి ఉన్నాయి')
})

test('Kannada: singular for 1, plural for 2', () => {
  assert.equal(count('kn', 'person', 1), '1 ವ್ಯಕ್ತಿ')
  assert.equal(count('kn', 'person', 2), '2 ಜನ')
  assert.equal(count('kn', 'problemFound', 1), '1 ಸಮಸ್ಯೆ')
  assert.equal(count('kn', 'problemFound', 2), '2 ಸಮಸ್ಯೆಗಳು')
  assert.equal(count('kn', 'stepOpen', 1), '1 ಹಂತ ಬಾಕಿ ಇದೆ')
  assert.equal(count('kn', 'stepOpen', 2), '2 ಹಂತಗಳು ಬಾಕಿ ಇವೆ')
  assert.equal(count('kn', 'tryLeft', 1), '1 ಪ್ರಯತ್ನ ಉಳಿದಿದೆ')
  assert.equal(count('kn', 'tryLeft', 2), '2 ಪ್ರಯತ್ನಗಳು ಉಳಿದಿವೆ')
})
