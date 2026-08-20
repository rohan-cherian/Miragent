/* §8 · 7, 9 — Modal and side panel. Both trap focus; Esc closes the topmost one
   without touching the underlying route (§5.4). Modals are never stacked >1. */

import React, { useEffect, useRef } from 'react'
import { Button } from './primitives.jsx'

function useFocusTrap(ref, onClose) {
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const prev = document.activeElement
    const focusables = () => node.querySelectorAll(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
    )
    const first = focusables()[0]
    ;(first || node).focus()

    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose?.() }
      if (e.key === 'Tab') {
        const els = [...focusables()]
        if (!els.length) return
        const i = els.indexOf(document.activeElement)
        if (e.shiftKey && (i <= 0)) { e.preventDefault(); els[els.length - 1].focus() }
        else if (!e.shiftKey && i === els.length - 1) { e.preventDefault(); els[0].focus() }
      }
    }
    node.addEventListener('keydown', onKey)
    return () => { node.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [ref, onClose])
}

export function Modal({ title, subtitle, onClose, footer, wide, children, labelledBy = 'modal-title' }) {
  const ref = useRef(null)
  useFocusTrap(ref, onClose)
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true"
           aria-labelledby={labelledBy} ref={ref} tabIndex={-1}>
        <div className="modal-head">
          <div className="row gap-3">
            <div className="grow">
              <h2 id={labelledBy}>{title}</h2>
              {subtitle && <div className="caption" style={{ marginTop: 4 }}>{subtitle}</div>}
            </div>
            <Button variant="ghost" onClick={onClose} aria-label="Close dialog">Esc</Button>
          </div>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

/** Right overlay for drill-downs. Origin scroll is preserved by the caller. */
export function SidePanel({ title, subtitle, onClose, wide, children, footer }) {
  const ref = useRef(null)
  useFocusTrap(ref, onClose)
  return (
    <>
      <div className="panel-scrim" onMouseDown={onClose} />
      <aside className={`side-panel ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true"
             aria-label={title} ref={ref} tabIndex={-1}>
        <div className="panel-head">
          <div className="grow">
            <h2>{title}</h2>
            {subtitle && <div className="caption" style={{ marginTop: 2 }}>{subtitle}</div>}
          </div>
          <Button variant="ghost" onClick={onClose} aria-label="Close panel">Esc</Button>
        </div>
        <div className="panel-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </aside>
    </>
  )
}
