// One audio at a time for the whole app. Any Listen button stops whatever is playing; "Listen to all" plays a
// queue of keys in order and can be stopped at any point. Components subscribe with useAudio().
import { useSyncExternalStore } from 'react'

type State = { key: string | null; queue: string[] } // key: what is playing now; queue: what plays after it

let state: State = { key: null, queue: [] }
let audio: HTMLAudioElement | null = null
let urls: Record<string, string> = {}
const listeners = new Set<() => void>()

function set(next: State): void {
  state = next
  listeners.forEach((l) => l())
}

function start(key: string, queue: string[]): void {
  audio?.pause()
  const el = new Audio(urls[key])
  audio = el
  const next = () => {
    if (audio !== el) return // stopped or replaced meanwhile
    const [head, ...rest] = state.queue
    if (head) start(head, rest)
    else { audio = null; set({ key: null, queue: [] }) }
  }
  el.onended = next
  el.onerror = next // no TTS on the server: skip rather than hang
  set({ key, queue })
  void el.play().catch(next)
}

export function play(key: string, url: string): void {
  urls[key] = url
  start(key, [])
}

export function playAll(items: [string, string][]): void {
  if (!items.length) return
  urls = { ...urls, ...Object.fromEntries(items) }
  start(items[0][0], items.slice(1).map(([k]) => k))
}

export function stop(): void {
  audio?.pause()
  audio = null
  set({ key: null, queue: [] })
}

export function useAudio(): State {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => { listeners.delete(l) } },
    () => state,
  )
}
