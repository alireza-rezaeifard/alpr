import { useState, useEffect } from 'react'
import { getSessions } from '../api'
import type { Session } from '../types'

function duration(s: Session): string {
  if (!s.started_at || !s.ended_at) return ''
  try {
    const secs = (new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 1000
    return `${secs.toFixed(0)}s`
  } catch {
    return ''
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'done': return 'var(--success)'
    case 'running': return 'var(--warning)'
    case 'error': return 'var(--danger)'
    default: return 'var(--text)'
  }
}

export default function Sessions() {
  const [sessions, setSessions] = useState<Session[]>([])

  useEffect(() => {
    getSessions(30).then(d => setSessions(d.data))
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
        <button onClick={() => getSessions(30).then(d => setSessions(d.data))} style={{
          padding: '8px 16px', borderRadius: 8, border: 'none',
          background: 'var(--primary)', color: 'white', cursor: 'pointer', fontSize: 13,
        }}>Refresh</button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Started</th>
              <th>Source</th>
              <th>Status</th>
              <th>Plates</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {sessions.length === 0 ? (
              <tr><td colSpan={5} className="empty-state">No sessions yet.</td></tr>
            ) : sessions.map(s => (
              <tr key={s.id}>
                <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{s.started_at?.slice(0, 19).replace('T', ' ')}</td>
                <td>{s.source_type?.charAt(0).toUpperCase() + s.source_type?.slice(1)}</td>
                <td style={{ color: statusColor(s.status) }}>{s.status}</td>
                <td>{s.total_plates}</td>
                <td>{duration(s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
