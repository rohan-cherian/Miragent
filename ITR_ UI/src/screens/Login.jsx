/* S-14 · Login & role selection (auth stub) [F-079, F-094].
   Scope Class: POC functional. Role selection IS the RBAC demonstration
   mechanism — switching role visibly changes the product. */

import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../shell/session.jsx'
import { ROLES } from '../contracts/rbac.js'
import { Button, ScopeBanner } from '../ui/primitives.jsx'
import { TENANT } from '../contracts/config.js'
import { ScopeClass } from '../contracts/state.js'
import { emit } from '../contracts/telemetry.js'

export default function Login() {
  const { role: current, signIn } = useSession()
  const [params] = useSearchParams()
  const next = params.get('next')
  const isSwitch = params.get('switch') === '1'
  const [picked, setPicked] = useState(current || ROLES[0].id)
  const nav = useNavigate()

  const go = () => {
    signIn(picked)
    emit('screen_load', { screen: 'S-14', role: picked })
    const home = ROLES.find((r) => r.id === picked).home
    nav(next || home, { replace: true })
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="row gap-3" style={{ marginBottom: 'var(--sp-2)' }}>
          <span className="brand-mark" aria-hidden="true">IT</span>
          <div className="grow">
            <div className="page-title">Motiveminds ITR</div>
            {/* The honesty chip starts here [F-121]. */}
            <div className="caption">{TENANT} · Synthetic data · six emulated source systems</div>
          </div>
          <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
        </div>

        <p className="muted" style={{ fontSize: 'var(--fs-table)' }}>
          {isSwitch
            ? 'Switching role. Your current role is marked. Nothing about the data changes — what changes is what you are permitted to see and do.'
            : 'Choose the role you want to enter the console as. Role drives navigation, permitted actions and the audit attribution of anything you do.'}
          {next && <> After you continue you will land on <span className="mono">{next}</span>.</>}
        </p>

        <div className="role-grid" role="radiogroup" aria-label="Role">
          {ROLES.map((r, i) => (
            <button
              key={r.id}
              className="role-card"
              role="radio"
              aria-checked={picked === r.id}
              autoFocus={i === 0}
              onClick={() => setPicked(r.id)}
              onDoubleClick={go}
              onKeyDown={(e) => { if (e.key === 'Enter') go() }}
            >
              <div className="row gap-2" style={{ width: '100%' }}>
                <span className="role-name">{r.name}</span>
                {current === r.id && <span className="chip chip-primary">current</span>}
              </div>
              <div className="caption">{r.description}</div>
              <div className="meta">Lands on <span className="mono">{r.home}</span> · audits as “{r.stubUser}”</div>
            </button>
          ))}
        </div>

        <div className="row gap-3" style={{ marginTop: 'var(--sp-5)' }}>
          <span className="caption grow">
            Stub authentication — POC. There are no password fields because there is no auth service;
            the stub changes identity and never bypasses a gate.
          </span>
          <Button variant="primary" size="lg" onClick={go}>Continue</Button>
        </div>
      </div>
    </div>
  )
}
