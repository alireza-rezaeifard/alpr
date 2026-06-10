import { useState, useEffect } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { getStats, getTimeline, getSources, getConfidence, getLetters, getDetections } from '../api'
import type { Stats, TimelineEntry, SourceEntry, ConfidenceEntry, LetterEntry, Detection } from '../types'
import PlateTemplate from './PlateTemplate'

const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7']

function StatCard({ label, value, color = '#3b82f6', sub = '' }: {
  label: string
  value: string | number
  color?: string
  sub?: string
}) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className="value" style={{ color }}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [confidence, setConfidence] = useState<ConfidenceEntry[]>([])
  const [letters, setLetters] = useState<LetterEntry[]>([])
  const [recent, setRecent] = useState<Detection[]>([])

  useEffect(() => {
    getStats().then(setStats)
    getTimeline(14).then(d => setTimeline(d.data))
    getSources().then(d => setSources(d.data))
    getConfidence().then(d => setConfidence(d.data))
    getLetters().then(d => setLetters(d.data))
    getDetections({ limit: 10 }).then(d => setRecent(d.data))
  }, [])

  if (!stats) return <div className="empty-state">Loading...</div>

  return (
    <div>
      <div className="stat-grid">
        <StatCard label="Total Detections" value={stats.total_detections} color="#3b82f6" sub={`${stats.detections_7d} in 7 days`} />
        <StatCard label="Unique Plates" value={stats.unique_plates} color="#22c55e" />
        <StatCard label="Sessions" value={stats.total_sessions} color="#f59e0b" sub={`${stats.sessions_7d} in 7 days`} />
        <StatCard label="Avg Confidence" value={stats.avg_confidence ? `${(stats.avg_confidence * 100).toFixed(1)}%` : 'N/A'} color="#22c55e" />
      </div>

      <div className="chart-grid chart-grid-2">
        <div className="chart-card">
          <h3>Detection Timeline (14 days)</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={timeline}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="dt" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
              <Line type="monotone" dataKey="cnt" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: '#3b82f6' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-card">
          <h3>By Source</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={sources} dataKey="cnt" nameKey="source_type" cx="50%" cy="50%" outerRadius={70}
                label={({ source_type, percent }: { source_type: string; percent: number }) =>
                  `${source_type} ${(percent * 100).toFixed(0)}%`}
              >
                {sources.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="chart-grid chart-grid-2-equal">
        <div className="chart-card">
          <h3>Confidence Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={confidence}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="bin" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
              <Bar dataKey="cnt" fill="#22c55e" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-card">
          <h3>Most Detected Plates</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={letters.slice(0, 10)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis dataKey="plate_persian" type="category" tick={{ fill: '#f1f5f9', fontSize: 11 }} tickLine={false} width={120} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
              <Bar dataKey="cnt" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="section-title">Recent Detections</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Plate</th>
              <th>Source</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {recent.length === 0 ? (
              <tr><td colSpan={4} className="empty-state">No detections yet.</td></tr>
            ) : recent.map(d => (
              <tr key={d.id}>
                <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{d.timestamp?.slice(0, 19).replace('T', ' ')}</td>
                <td><PlateTemplate plateText={d.plate_dtrb} size="sm" /></td>
                <td>{d.source_type?.charAt(0).toUpperCase() + d.source_type?.slice(1)}</td>
                <td style={{ color: 'var(--success)' }}>{(d.confidence * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
