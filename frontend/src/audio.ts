// One audio at a time for the whole app. Any Listen button stops whatever is playing; "Listen to all" plays a
// queue of keys in order and can be stopped at any point. Components subscribe with useAudio().
//
// Phones: mobile browsers (iPhone Safari above all) refuse to start audio that was not started by a tap, and an
// answer arrives seconds after the tap that asked for it. So the whole app plays through ONE audio element, and
// `unlock()` (called inside the taps that lead to a spoken answer: the mic and Send) plays a moment of silence on it;
// Safari then lets that element play the answer later. If the browser still refuses, the key is marked `blocked`
// and its Listen button turns into "Tap to listen" instead of failing silently.
import { useSyncExternalStore } from 'react'
import { playableUrl } from './api'

// key: what is playing (or loading) now; queue: what plays after it; group: the 'Listen to all' that started it;
// loading: fetched but not sounding yet; blocked: the key the browser would not play without a tap
type State = { key: string | null; queue: string[]; group: string | null; loading: boolean; blocked: string | null }

const IDLE: State = { key: null, queue: [], group: null, loading: false, blocked: null }
let state: State = IDLE
let urls: Record<string, string> = {}
let generation = 0 // each start/stop gets a new one; handlers of an older one do nothing
let shared: HTMLAudioElement | null = null
const listeners = new Set<() => void>()

function set(next: State): void {
  state = next
  listeners.forEach((l) => l())
}

function element(): HTMLAudioElement {
  if (!shared) {
    shared = new Audio()
    shared.preload = 'auto'
  }
  return shared
}

const SILENCE = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA='

// Call inside a tap. Does nothing while something is playing (that element is already allowed to play).
export function unlock(): void {
  if (state.key) return
  const el = element()
  el.src = SILENCE
  el.play().catch(() => { /* nothing to unlock here */ })
}

function start(key: string, queue: string[], group: string | null): void {
  const gen = ++generation
  const el = element()
  el.pause()
  const next = () => {
    if (gen !== generation) return // stopped or replaced meanwhile
    const [head, ...rest] = state.queue
    if (head) start(head, rest, state.group)
    else set(IDLE)
  }
  el.onended = next
  el.onerror = next // no TTS on the server: skip rather than hang
  el.onplaying = () => { if (gen === generation && state.loading) set({ ...state, loading: false }) }
  set({ key, queue, group, loading: true, blocked: null })
  playableUrl(urls[key]) // case-file audio needs the login header: fetched first
    .then((src) => { if (gen !== generation) return; el.src = src; return el.play() })
    .catch((e: unknown) => {
      if (gen !== generation) return
      if (e instanceof DOMException && e.name === 'NotAllowedError') set({ ...IDLE, blocked: key }) // "Tap to listen"
      else next()
    })
}

export function play(key: string, url: string): void {
  urls[key] = url
  start(key, [], null)
}

export function playAll(group: string, items: [string, string][]): void {
  if (!items.length) return
  urls = { ...urls, ...Object.fromEntries(items) }
  start(items[0][0], items.slice(1).map(([k]) => k), group)
}

export function stop(): void {
  generation++
  shared?.pause()
  set(IDLE)
}

export function useAudio(): State {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => { listeners.delete(l) } },
    () => state,
  )
}
