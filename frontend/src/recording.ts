// Pure helpers for asking by voice (ui/askVoice.ts), kept free of the API client so node tests can load them.
import type { Strings } from './i18n'

export const MAX_SECONDS = 30
// Android Chrome records WebM/Opus; iPhone Safari only MP4/AAC. The backend converts either with ffmpeg.
const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4', 'audio/aac']

export function pickMimeType(supported: (type: string) => boolean): string {
  return MIME_TYPES.find((m) => supported(m)) ?? ''
}

// A refused permission vs. no usable microphone (getUserMedia's error names).
export function micErrorNote(t: Pick<Strings, 'micDenied' | 'noMic'>, error: unknown): string {
  const name = (error as { name?: string } | null)?.name ?? ''
  return name === 'NotAllowedError' || name === 'SecurityError' ? t.micDenied : t.noMic
}

export const clock = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The level meter: -60 dBFS (room hush) to -10 dBFS (loud speech) as 0-1, so normal speech moves the bar.
export function meterLevel(rms: number): number {
  const db = rms > 0 ? 20 * Math.log10(rms) : -100
  return Math.max(0, Math.min(1, (db + 60) / 50))
}
