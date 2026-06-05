import { useState, useRef, useEffect, useCallback } from 'react'
import { detectImage, detectVideo, getVideoTaskStatus, stopVideoTask, startRTSP, getRTSPTaskStatus, stopRTSPTask } from '../api'
import type { PlateResult, VideoTaskStatus, RTSPTaskStatus } from '../types'

const SUB_TABS = ['Image', 'Video', 'RTSP'] as const
type SubTab = (typeof SUB_TABS)[number]

/* ─────────────── Image detection ─────────────── */

function ImageTab() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [result, setResult] = useState<{ annotated: string; plates: PlateResult[] } | null>(null)
  const [loading, setLoading] = useState(false)

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setPreview(URL.createObjectURL(f))
    setResult(null)
  }

  const runDetect = async () => {
    if (!file) return
    setLoading(true)
    try {
      const res = await detectImage(file)
      setResult({ annotated: res.annotated, plates: res.plates })
    } catch (e) {
      alert(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 300px' }}>
        <div style={{ marginBottom: 12 }}>
          <input type="file" accept="image/*" onChange={onFileChange}
            style={{ color: 'var(--text)', fontSize: 13 }} />
        </div>
        {preview && <img src={preview} alt="input" style={{ width: '100%', maxHeight: 300, objectFit: 'contain', borderRadius: 8, border: '1px solid var(--border)' }} />}
        <button onClick={runDetect} disabled={!file || loading} style={{
          marginTop: 12, padding: '10px 24px', borderRadius: 8, border: 'none',
          background: loading ? 'var(--surface-2)' : 'var(--primary)', color: 'white',
          cursor: loading ? 'not-allowed' : 'pointer', fontSize: 14,
        }}>
          {loading ? 'Processing...' : 'Detect'}
        </button>
      </div>

      <div style={{ flex: '1 1 300px' }}>
        {result && (
          <>
            <img src={result.annotated} alt="result" style={{ width: '100%', maxHeight: 300, objectFit: 'contain', borderRadius: 8, border: '1px solid var(--border)' }} />
            {result.plates.length > 0 && (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Plate</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.plates.map((p, i) => (
                      <tr key={i}>
                        <td>{p.plate_persian}</td>
                        <td style={{ color: 'var(--success)' }}>{(p.confidence * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {result.plates.length === 0 && <p style={{ color: 'var(--text-muted)', marginTop: 12 }}>No license plate detected.</p>}
          </>
        )}
      </div>
    </div>
  )
}

/* ─────────────── Video detection ─────────────── */

function VideoTab() {
  const [file, setFile] = useState<File | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [status, setStatus] = useState<VideoTaskStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const poll = useCallback(async (tid: string) => {
    try {
      const s = await getVideoTaskStatus(tid)
      setStatus(s)
      if (s.status === 'done' || s.status === 'error' || s.status === 'cancelled') {
        if (intervalRef.current) clearInterval(intervalRef.current)
        setLoading(false)
      }
    } catch { /* ignore */ }
  }, [])

  const start = async () => {
    if (!file) return
    setLoading(true)
    setStatus(null)
    try {
      const res = await detectVideo(file, 30, false)
      setTaskId(res.task_id)
      intervalRef.current = setInterval(() => poll(res.task_id), 1000)
    } catch (e) {
      alert(String(e))
      setLoading(false)
    }
  }

  const stop = async () => {
    if (taskId) {
      await stopVideoTask(taskId)
      if (intervalRef.current) clearInterval(intervalRef.current)
      setLoading(false)
    }
  }

  useEffect(() => {
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [])

  const pct = status?.total_frames
    ? Math.round((status.frame_idx / status.total_frames) * 100)
    : 0

  const outputUrl = status?.output_path
    ? `/media/${status.output_path.split(/[/\\]/).pop()}`
    : null

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 300px' }}>
        <div style={{ marginBottom: 12 }}>
          <input type="file" accept="video/*" onChange={e => { setFile(e.target.files?.[0] ?? null); setStatus(null) }}
            style={{ color: 'var(--text)', fontSize: 13 }} />
        </div>
        {file && <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 8 }}>{file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)</p>}
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={start} disabled={!file || loading} style={{
            padding: '10px 24px', borderRadius: 8, border: 'none',
            background: loading ? 'var(--surface-2)' : 'var(--primary)', color: 'white',
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 14,
          }}>
            {loading ? 'Processing...' : 'Start'}
          </button>
          <button onClick={stop} disabled={!loading} style={{
            padding: '10px 24px', borderRadius: 8, border: '1px solid var(--danger)',
            background: 'transparent', color: 'var(--danger)',
            cursor: loading ? 'pointer' : 'not-allowed', fontSize: 14,
          }}>Stop</button>
        </div>

        {status && (status.status === 'processing' || status.status === 'queued') && (
          <div style={{ marginTop: 12 }}>
            <div style={{ height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: 'var(--primary)', borderRadius: 4, transition: 'width 0.5s' }} />
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>
              {status.frame_idx} / {status.total_frames} frames ({pct}%)
            </p>
          </div>
        )}

        {status?.status === 'done' && outputUrl && (
          <div style={{ marginTop: 12 }}>
            <a href={outputUrl} download style={{ color: 'var(--primary-light)', fontSize: 14 }}>
              Download Processed Video
            </a>
          </div>
        )}

        {status?.status === 'error' && (
          <p style={{ color: 'var(--danger)', marginTop: 8 }}>Error: {status.error}</p>
        )}
      </div>

      <div style={{ flex: '1 1 300px' }}>
        {status && status.plate_log && status.plate_log.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Frame</th>
                  <th>Time</th>
                  <th>Plate</th>
                  <th>Conf</th>
                </tr>
              </thead>
              <tbody>
                {status.plate_log.slice(-20).reverse().map((e, i) => (
                  <tr key={i}>
                    <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{e.frame}</td>
                    <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{e.time}</td>
                    <td>{e.plate_text}</td>
                    <td style={{ color: 'var(--success)' }}>{e.confidence.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(!status || !status.plate_log || status.plate_log.length === 0) && (
          <p style={{ color: 'var(--text-muted)', padding: 20 }}>No detections yet.</p>
        )}
      </div>
    </div>
  )
}

/* ─────────────── RTSP detection ─────────────── */

function RTSPTab() {
  const [urlInput, setUrlInput] = useState('')
  const [taskId, setTaskId] = useState<string | null>(null)
  const [status, setStatus] = useState<RTSPTaskStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const poll = useCallback(async (tid: string) => {
    try {
      const s = await getRTSPTaskStatus(tid)
      setStatus(s)
      if (s.status.startsWith('error')) {
        if (intervalRef.current) clearInterval(intervalRef.current)
        setLoading(false)
      }
    } catch { /* ignore */ }
  }, [])

  const start = async () => {
    if (!urlInput.trim()) return
    setLoading(true)
    setStatus(null)
    try {
      const res = await startRTSP(urlInput.trim(), false, 15)
      setTaskId(res.task_id)
      intervalRef.current = setInterval(() => poll(res.task_id), 1000)
    } catch (e) {
      alert(String(e))
      setLoading(false)
    }
  }

  const stop = async () => {
    if (taskId) {
      await stopRTSPTask(taskId)
      if (intervalRef.current) clearInterval(intervalRef.current)
      setLoading(false)
    }
  }

  useEffect(() => {
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [])

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 300px' }}>
        <input type="text" placeholder="rtsp://username:password@192.168.1.100:554/stream"
          value={urlInput} onChange={e => setUrlInput(e.target.value)}
          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)',
            background: 'var(--surface)', color: 'var(--text)', fontSize: 13, marginBottom: 12 }} />
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={start} disabled={!urlInput.trim() || loading} style={{
            padding: '10px 24px', borderRadius: 8, border: 'none',
            background: loading ? 'var(--surface-2)' : 'var(--primary)', color: 'white',
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 14,
          }}>
            {loading ? 'Connecting...' : 'Start Stream'}
          </button>
          <button onClick={stop} disabled={!loading && !status} style={{
            padding: '10px 24px', borderRadius: 8, border: '1px solid var(--danger)',
            background: 'transparent', color: 'var(--danger)',
            cursor: 'pointer', fontSize: 14,
          }}>Stop</button>
        </div>

        <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 8 }}>
          Status: {status?.status ?? 'Not started'}
        </p>

        {status?.history && status.history.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Plate</th>
                  <th>Count</th>
                  <th>Conf</th>
                </tr>
              </thead>
              <tbody>
                {status.history.slice().reverse().map((p, i) => (
                  <tr key={i}>
                    <td>{p.dtrb_text}</td>
                    <td>{p.count}</td>
                    <td style={{ color: 'var(--success)' }}>{(p.confidence * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ flex: '1 1 300px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {status?.annotated ? (
          <img src={status.annotated} alt="live feed" style={{
            width: '100%', maxHeight: 360, objectFit: 'contain',
            borderRadius: 8, border: '1px solid var(--border)',
          }} />
        ) : (
          <div style={{
            width: '100%', height: 260, borderRadius: 8, border: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--text-muted)', fontSize: 13,
          }}>
            {loading ? 'Waiting for stream...' : 'No stream active'}
          </div>
        )}
      </div>
    </div>
  )
}

/* ─────────────── Main Detection component ─────────────── */

export default function Detection() {
  const [sub, setSub] = useState<SubTab>('Image')

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--border)' }}>
        {SUB_TABS.map(t => (
          <button key={t} onClick={() => setSub(t)} style={{
            background: 'none', border: 'none', color: sub === t ? 'var(--primary-light)' : 'var(--text-muted)',
            padding: '10px 20px', fontSize: 14, cursor: 'pointer',
            borderBottom: sub === t ? '2px solid var(--primary-light)' : '2px solid transparent',
            marginBottom: -1,
          }}>
            {t === 'Image' ? '\u{1F5BC}  ' : t === 'Video' ? '\u{1F3AC}  ' : '\u{1F4E1}  '}{t}
          </button>
        ))}
      </div>
      {sub === 'Image' && <ImageTab />}
      {sub === 'Video' && <VideoTab />}
      {sub === 'RTSP' && <RTSPTab />}
    </div>
  )
}
