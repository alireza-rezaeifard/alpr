import { useState, useEffect, useCallback } from 'react'
import { getDetections } from '../api'
import type { Detection } from '../types'
import PlateTemplate from './PlateTemplate'

export default function History() {
  const [data, setData] = useState<Detection[]>([])
  const [total, setTotal] = useState(0)
  const [source, setSource] = useState('all')
  const [search, setSearch] = useState('')

  const load = useCallback(() => {
    getDetections({ limit: 200, source_type: source, search }).then(d => {
      setData(d.data)
      setTotal(d.total)
    })
  }, [source, search])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="filters">
        <select value={source} onChange={e => setSource(e.target.value)}>
          <option value="all">All Sources</option>
          <option value="image">Image</option>
          <option value="video">Video</option>
          <option value="rtsp">RTSP</option>
        </select>
        <input
          type="text"
          placeholder="Search plate text..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()}
        />
        <button onClick={load} style={{
          padding: '8px 16px', borderRadius: 8, border: 'none',
          background: 'var(--primary)', color: 'white', cursor: 'pointer', fontSize: 13,
        }}>Refresh</button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Plate</th>
              <th>Source</th>
              <th>Confidence</th>
              <th>File</th>
            </tr>
          </thead>
          <tbody>
            {data.length === 0 ? (
              <tr><td colSpan={5} className="empty-state">No records found.</td></tr>
            ) : data.map(d => (
              <tr key={d.id}>
                <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{d.timestamp?.slice(0, 19).replace('T', ' ')}</td>
                <td><PlateTemplate plateText={d.plate_dtrb} size="sm" /></td>
                <td>{d.source_type?.charAt(0).toUpperCase() + d.source_type?.slice(1)}</td>
                <td style={{ color: 'var(--success)' }}>{(d.confidence * 100).toFixed(1)}%</td>
                <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{d.source_file?.split(/[/\\]/).pop() || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="total-count">{total} total records</div>
      </div>
    </div>
  )
}
