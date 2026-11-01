import { play, stop, useAudio } from '../audio'
import type { Strings } from '../i18n'
import { Play, Stop } from './Icons'

// Listen, or Stop while this one is playing (or loading). Starting it stops anything else. If the browser refused to
// play it without a tap (a spoken answer on a phone), it asks for that tap: "Tap to listen".
export default function ListenButton({ t, audioKey, url, label }: { t: Strings; audioKey: string; url: string; label?: string }) {
  const { key, loading, blocked } = useAudio()
  const playing = key === audioKey
  const tap = blocked === audioKey
  const text = playing ? t.stop : tap ? t.tapToListen : t.play
  return (
    <button type="button" className={`listen${playing ? ' playing' : ''}${tap ? ' blocked' : ''}`} aria-pressed={playing}
      aria-busy={playing && loading} aria-label={playing ? t.stop : label ? `${text}: ${label}` : text}
      onClick={() => (playing ? stop() : play(audioKey, url))}>
      {playing ? <Stop /> : <Play />}<span>{text}</span>{playing && loading && <span className="dots" aria-hidden="true" />}
    </button>
  )
}
