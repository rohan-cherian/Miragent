/* Auth stub session (S-14 / F-079). The stub changes identity; it NEVER bypasses
   a gate [NFR-13]. Audit rows attribute to the named stub user of the role. */

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Role, roleMeta } from '../contracts/rbac.js'

const KEY = 'itr.session.role'
const SessionCtx = createContext(null)

export function SessionProvider({ children }) {
  const [role, setRole] = useState(() => sessionStorage.getItem(KEY) || null)
  // Per-role state isolation (§10.15 NFR): queue position and read notifications.
  const [perRole, setPerRole] = useState({})

  useEffect(() => {
    if (role) sessionStorage.setItem(KEY, role)
    else sessionStorage.removeItem(KEY)
  }, [role])

  const value = useMemo(() => ({
    role,
    meta: role ? roleMeta(role) : null,
    stubUser: role ? roleMeta(role).stubUser : null,
    signIn: setRole,
    signOut: () => setRole(null),
    isDemo: role === Role.DEMO,
    state: perRole[role] || {},
    setState: (patch) => setPerRole((p) => ({ ...p, [role]: { ...(p[role] || {}), ...patch } })),
  }), [role, perRole])

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>
}

export const useSession = () => {
  const ctx = useContext(SessionCtx)
  if (!ctx) throw new Error('useSession must be used inside SessionProvider')
  return ctx
}
