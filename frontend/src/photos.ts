// Photo mode helpers: photos are resized in the browser before upload. Drawing the photo on a canvas and encoding
// a new JPEG keeps only the pixels, so EXIF data (GPS location, phone model, time) never leaves the phone.

export const MAX_PHOTOS = 12
export const PHOTO_LONG_SIDE = 2000
const JPEG_QUALITY = 0.88

// Size that fits `longSide` on the long edge (never upscaled).
export function fitLongSide(width: number, height: number, longSide = PHOTO_LONG_SIDE): { width: number; height: number } {
  const scale = Math.min(1, longSide / Math.max(width, height))
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

// How many photos are fully sent when `fraction` of the request body has gone (the photos are sent in order).
export function photosSent(fraction: number, sizes: number[]): number {
  const total = sizes.reduce((a, b) => a + b, 0)
  let sent = 0
  let done = 0
  for (const size of sizes) {
    sent += size
    if (sent <= fraction * total + 1) done += 1
    else break
  }
  return done
}

// The photo, turned the way the phone held it (EXIF orientation), at most PHOTO_LONG_SIDE px, as a fresh JPEG
// without any EXIF data.
export async function preparePhoto(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  const { width, height } = fitLongSide(bitmap.width, bitmap.height)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas not available')
  ctx.drawImage(bitmap, 0, 0, width, height)
  bitmap.close()
  return new Promise((resolve, reject) => canvas.toBlob(
    (blob) => (blob ? resolve(blob) : reject(new Error('could not encode the photo'))), 'image/jpeg', JPEG_QUALITY))
}
