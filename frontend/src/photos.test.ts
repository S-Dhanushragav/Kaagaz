import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fitLongSide, photosSent } from './photos.ts'

test('photos are scaled to 2000 px on the long edge, never up', () => {
  assert.deepEqual(fitLongSide(4000, 3000), { width: 2000, height: 1500 })
  assert.deepEqual(fitLongSide(3000, 4000), { width: 1500, height: 2000 })
  assert.deepEqual(fitLongSide(1200, 900), { width: 1200, height: 900 })
})

test('uploading N of M counts whole photos sent', () => {
  const sizes = [100, 300, 100]
  assert.equal(photosSent(0, sizes), 0)
  assert.equal(photosSent(0.19, sizes), 0)
  assert.equal(photosSent(0.2, sizes), 1)
  assert.equal(photosSent(0.79, sizes), 1)
  assert.equal(photosSent(0.8, sizes), 2)
  assert.equal(photosSent(1, sizes), 3)
})
