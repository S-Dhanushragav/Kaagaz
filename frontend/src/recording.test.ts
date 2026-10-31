import assert from 'node:assert/strict'
import { test } from 'node:test'
import { clock, meterLevel, micErrorNote, pickMimeType } from './recording.ts'

test('Chrome records WebM/Opus, Safari MP4/AAC, and an unknown browser its default', () => {
  assert.equal(pickMimeType((m) => m.startsWith('audio/webm')), 'audio/webm;codecs=opus')
  assert.equal(pickMimeType((m) => m.startsWith('audio/mp4')), 'audio/mp4;codecs=mp4a.40.2')
  assert.equal(pickMimeType(() => false), '')
})

test('a refused microphone and a missing one get different messages', () => {
  const t = { micDenied: 'denied', noMic: 'none' }
  assert.equal(micErrorNote(t, { name: 'NotAllowedError' }), 'denied')
  assert.equal(micErrorNote(t, { name: 'NotFoundError' }), 'none')
  assert.equal(micErrorNote(t, null), 'none')
})

test('the timer shows minutes and seconds', () => {
  assert.equal(clock(0), '0:00')
  assert.equal(clock(9.7), '0:09')
  assert.equal(clock(30), '0:30')
})

test('the level meter moves with speech and stays empty in silence', () => {
  assert.equal(meterLevel(0), 0)
  assert.equal(meterLevel(0.0005), 0) // about -66 dBFS
  const speech = meterLevel(0.05) // about -26 dBFS
  assert.ok(speech > 0.5 && speech < 0.8)
  assert.equal(meterLevel(1), 1)
})
