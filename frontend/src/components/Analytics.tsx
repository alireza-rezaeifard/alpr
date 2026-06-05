import { useState, useEffect } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { getTimeline, getSources, getConfidence, getLetters } from '../api'
import type { TimelineEntry, SourceEntry, ConfidenceEntry, LetterEntry } from '../types'

const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7']

export default function Analytics() {
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [confidence, setConfidence] = useState<ConfidenceEntry[]>([])
  const [letters, setLetters] = useState<LetterEntry[]>([])
  const [days, setDays] = useState(14)

  useEffect(() => {
    getTimeline(days).then(d => setTimeline(d.data))
    getSources().then(d => setSources(d.data))
    getConfidence().then(d => setConfidence(d.data))
    getLetters().then(d => setLetters(d.data))
  }, [days])

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <label style={{ color: 'var(--text-muted)', fontSize: 13 }}>Timeline:</label>
        <select value={days} onChange={e => setDays(Number(e.target.value))} style={{
          padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)',
          background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
        }}>
          <option value={7}>7 days</option>
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
        </select>
      </div>

      <div className="chart-grid" style={{ gridTemplateColumns: '1fr' }}>
        <div className="chart-card">
          <h3>Detection Timeline</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={timeline}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="dt" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
              <Line type="monotone" dataKey="cnt" stroke="#3b82f6" strokeWidth={2} dot={{ r: 4, fill: '#3b82f6' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="chart-grid chart-grid-2-equal">
        <div className="chart-card">
          <h3>By Source</h3>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={sources} dataKey="cnt" nameKey="source_type" cx="50%" cy="50%" outerRadius={90}
                label={({ source_type, cnt }: { source_type: string; cnt: number }) => `${source_type}: ${cnt}`}
              >
                {sources.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-card">
          <h3>Confidence Distribution</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={confidence}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="bin" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
              <Bar dataKey="cnt" fill="#22c55e" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="chart-card">
        <h3>Most Detected Plates</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={letters.slice(0, 15)} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
            <YAxis dataKey="plate_persian" type="category" tick={{ fill: '#f1f5f9', fontSize: 11 }} tickLine={false} width={140} />
            <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8, color: '#f1f5f9' } as React.CSSProperties} />
            <Bar dataKey="cnt" fill="#3b82f6" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
