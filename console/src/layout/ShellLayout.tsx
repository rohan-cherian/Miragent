import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { NAV_ITEMS } from '../nav'

export function ShellLayout() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen flex bg-surface">
      <aside
        className="hidden md:flex flex-col border-r border-line bg-surface-raised"
        style={{ width: 'var(--sidebar-width)' }}
      >
        <div className="px-5 pt-6 pb-4 border-b border-line">
          <p className="font-display text-2xl text-ink tracking-tight">Miragent</p>
          <p className="text-xs text-ink-muted mt-1">Console · demo shell</p>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  'block rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent-soft text-accent font-medium'
                    : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
                ].join(' ')
              }
            >
              <span className="block">{item.label}</span>
              {item.scene ? (
                <span className="block text-[11px] text-ink-faint mt-0.5">{item.scene}</span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-line">
          <p className="text-xs text-ink-muted truncate">{user?.email}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-2 text-xs text-accent hover:underline"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="md:hidden flex items-center justify-between px-4 py-3 border-b border-line bg-surface-raised">
          <p className="font-display text-xl">Miragent</p>
          <button type="button" onClick={logout} className="text-xs text-accent">
            Sign out
          </button>
        </header>

        {/* Mobile nav — simple horizontal scroll, no component library */}
        <div className="md:hidden overflow-x-auto border-b border-line bg-surface-raised">
          <div className="flex gap-1 px-2 py-2 min-w-max">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    'whitespace-nowrap rounded-full px-3 py-1.5 text-xs',
                    isActive ? 'bg-accent text-white' : 'bg-surface-sunken text-ink-muted',
                  ].join(' ')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>

        <main className="flex-1 p-6 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
