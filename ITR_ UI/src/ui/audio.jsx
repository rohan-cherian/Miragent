/* §8.14 · Call player with synced transcript (S-12).
   Per-word confidence is the treatment: low-confidence words are dotted-underlined
   AND carry a tooltip with the numeric — never colour alone.
   There is deliberately NO "summarise audio" control: audio never reaches a
   model, and the absence of the control is the guarantee [F-137, NFR-39].

   The audio itself is simulated with a clock rather than a media element — the
   fixture ships word timings over a generated artefact, labelled in LANE_NOTES. */

import React, { useEffect, useRef, useState } from 'react'
import { Button, Chip } from './primitives.jsx'
import { Notice } from './feedback.jsx'

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export function CallPlayer({ call, onClose, startAt = 0 }) {
  const [t, setT] = useState(startAt)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(1)
  const [urlRefreshed, setUrlRefreshed] = useState(false)
  const raf = useRef(null)

  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const tick = (now) => {
      const dt = ((now - last) / 1000) * rate
      last = now
      setT((prev) => {
        const next = prev + dt
        if (next >= call.duration_sec) { setPlaying(false); return call.duration_sec }
        // Signed URL expiry mid-session → transparent refresh, position preserved.
        if (prev < call.signed_url_expires_in_sec && next >= call.signed_url_expires_in_sec) {
          setUrlRefreshed(true)
        }
        return next
      })
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing, rate, call])

  const currentTurn = [...call.turns].reverse().find((x) => t >= x.t) || call.turns[0]

  const onKey = (e) => {
    if (e.key === ' ') { e.preventDefault(); setPlaying((v) => !v) }
    if (e.key === 'ArrowLeft') { e.preventDefault(); setT((v) => Math.max(0, v - 10)) }
    if (e.key === 'ArrowRight') { e.preventDefault(); setT((v) => Math.min(call.duration_sec, v + 10)) }
    if (e.key === 'Escape') onClose?.()
  }

  const bars = 90
  return (
    <div className="player" onKeyDown={onKey} tabIndex={0} role="group" aria-label="Call player with synced transcript">
      <div className="player-bar">
        <Button variant="secondary" size="sm" onClick={() => setPlaying((v) => !v)}
                aria-label={playing ? 'Pause' : 'Play'}>{playing ? '❚❚' : '▶'}</Button>
        <Button variant="ghost" size="sm" onClick={() => setT((v) => Math.max(0, v - 10))} aria-label="Back 10 seconds">−10s</Button>
        <Button variant="ghost" size="sm" onClick={() => setT((v) => Math.min(call.duration_sec, v + 10))} aria-label="Forward 10 seconds">+10s</Button>

        <div
          className="wave"
          role="slider"
          aria-label="Seek"
          aria-valuemin={0} aria-valuemax={call.duration_sec} aria-valuenow={Math.round(t)}
          aria-valuetext={mmss(t)}
          tabIndex={0}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            setT(((e.clientX - rect.left) / rect.width) * call.duration_sec)
          }}
        >
          {Array.from({ length: bars }).map((_, i) => {
            const frac = i / bars
            // Deterministic pseudo-waveform: shape follows the turn structure.
            const at = frac * call.duration_sec
            const inTurn = call.turns.some((x) => at >= x.t && at < x.t + 12)
            const h = (inTurn ? 40 : 12) + ((i * 37) % 23)
            return <span key={i} className={`wave-bar ${frac <= t / call.duration_sec ? 'played' : ''}`}
                         style={{ height: `${h}%` }} />
          })}
        </div>

        <span className="caption num" style={{ minWidth: 84, textAlign: 'right' }}>
          {mmss(t)} / {mmss(call.duration_sec)}
        </span>
        <div className="row gap-1">
          {[1, 1.5, 2].map((r) => (
            <Button key={r} variant={rate === r ? 'primary' : 'ghost'} size="sm" onClick={() => setRate(r)}>{r}×</Button>
          ))}
        </div>
        {onClose && <Button variant="ghost" size="sm" onClick={onClose}>Collapse</Button>}
      </div>

      <div className="row gap-2 wrap" style={{ padding: '0 var(--sp-3) var(--sp-2)' }}>
        <Chip icon="⌬" tone="emulated">Emulated ASR</Chip>
        <span className="meta">{call.asr_model} · avg confidence {call.asr_confidence_avg.toFixed(2)}</span>
        <span className="meta">{call.wer_note}</span>
      </div>

      {urlRefreshed && (
        <div style={{ padding: '0 var(--sp-3) var(--sp-2)' }}>
          <Notice tone="info" icon="↻">
            The signed audio URL expired and was refreshed transparently. Playback position was preserved.
          </Notice>
        </div>
      )}

      <div className="transcript">
        {call.turns.map((turn, i) => {
          const speaker = call.speakers.find((s) => s.id === turn.speaker)
          return (
            <div
              key={i}
              className={`turn ${currentTurn === turn ? 'current' : ''}`}
              onClick={() => setT(turn.t)}
              role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') setT(turn.t) }}
              aria-label={`Jump to ${mmss(turn.t)}, ${speaker?.label}`}
            >
              <span className="meta num">{mmss(turn.t)}</span>
              <span className="caption strong">{speaker?.label}</span>
              <span>
                {turn.words.map(([w, c], j) => (
                  c < 0.75
                    ? <span key={j} className="word-low"
                            title={`ASR confidence ${c.toFixed(2)} — this word may be misread`}>{w} </span>
                    : <React.Fragment key={j}>{w} </React.Fragment>
                ))}
              </span>
            </div>
          )
        })}
      </div>

      <div className="caption" style={{ padding: 'var(--sp-2) var(--sp-3)', borderTop: '1px solid var(--border)' }}>
        Transport: <span className="kbd">Space</span> play/pause · <span className="kbd">←</span>/<span className="kbd">→</span> ±10s ·
        the transcript is the accessible equivalent of the audio. Analysis actions operate on transcript text only —
        no control sends audio to a model.
      </div>
    </div>
  )
}
