import { play, stop, useAudio } from '../audio'
import type { Strings } from '../i18n'
import { Play, Stop } from './Icons'

// Listen, or Stop while this one is playing. Starting it stops anything else.
export default function ListenButton({ t, audioKey, url, label }: { t: Strings; audioKey: string; url: string; label?: string }) {
  const { key } = useAudio()
  const playing = key === audioKey
  return (
    <button type="button" className={playing ? 'listen playing' : 'listen'} aria-pressed={playing}
      aria-label={playing ? t.stop : label ? `${t.play}: ${label}` : t.play}
      onClick={() => (playing ? stop() : play(audioKey, url))}>
      {playing ? <Stop /> : <Play />}<span>{playing ? t.stop : t.play}</span>
    </button>
  )
}
