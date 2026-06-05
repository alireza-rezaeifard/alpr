import { useState } from 'react'
import Dashboard from './components/Dashboard'
import Analytics from './components/Analytics'
import History from './components/History'
import Sessions from './components/Sessions'
import Detection from './components/Detection'

const TABS = [
  { key: 'detection' as const, label: 'Detection' },
  { key: 'dashboard' as const, label: 'Dashboard' },
  { key: 'analytics' as const, label: 'Analytics' },
  { key: 'history' as const, label: 'History' },
  { key: 'sessions' as const, label: 'Sessions' },
]

type TabKey = (typeof TABS)[number]['key']

export default function App() {
  const [tab, setTab] = useState<TabKey>('detection')

  return (
    <div className="layout">
      <div className="header">
        <div>
          <h1>Persian License Plate Recognition</h1>
          <div className="sub">Detection &amp; Analytics Dashboard</div>
        </div>
      </div>

      <div className="nav">
        {TABS.map(t => (
          <button
            key={t.key}
            className={tab === t.key ? 'active' : ''}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'detection' && <Detection />}
      {tab === 'dashboard' && <Dashboard />}
      {tab === 'analytics' && <Analytics />}
      {tab === 'history' && <History />}
      {tab === 'sessions' && <Sessions />}
    </div>
  )
}
