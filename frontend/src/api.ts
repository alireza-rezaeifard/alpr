import type {
  Stats, DetectionsResponse, TimelineEntry, SourceEntry, ConfidenceEntry,
  LetterEntry, Session, GetDetectionsParams,
  DetectImageResponse, VideoTaskResponse, VideoTaskStatus,
  RTSPTaskResponse, RTSPTaskStatus,
} from './types'

const BASE = '/api'

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export function getStats(): Promise<Stats> {
  return fetchJSON<Stats>('/stats')
}

export function getDetections(params: GetDetectionsParams = {}): Promise<DetectionsResponse> {
  const q = new URLSearchParams()
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  if (params.source_type && params.source_type !== 'all') q.set('source_type', params.source_type)
  if (params.search) q.set('search', params.search)
  return fetchJSON<DetectionsResponse>(`/detections?${q}`)
}

export function getTimeline(days = 14): Promise<{ data: TimelineEntry[] }> {
  return fetchJSON<{ data: TimelineEntry[] }>(`/detections/timeline?days=${days}`)
}

export function getLetters(): Promise<{ data: LetterEntry[] }> {
  return fetchJSON<{ data: LetterEntry[] }>('/detections/letters')
}

export function getSources(): Promise<{ data: SourceEntry[] }> {
  return fetchJSON<{ data: SourceEntry[] }>('/detections/sources')
}

export function getConfidence(): Promise<{ data: ConfidenceEntry[] }> {
  return fetchJSON<{ data: ConfidenceEntry[] }>('/detections/confidence')
}

export function getSessions(limit = 20): Promise<{ data: Session[] }> {
  return fetchJSON<{ data: Session[] }>(`/sessions?limit=${limit}`)
}

// ── Detection API ──

export async function detectImage(file: File): Promise<DetectImageResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/detect/image`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Detection error: ${res.status}`)
  return res.json()
}

export async function detectVideo(file: File, skipFrames = 30, fastMode = false): Promise<VideoTaskResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('skip_frames', String(skipFrames))
  form.append('fast_mode', String(fastMode))
  const res = await fetch(`${BASE}/detect/video`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Detection error: ${res.status}`)
  return res.json()
}

export function getVideoTaskStatus(taskId: string): Promise<VideoTaskStatus> {
  return fetchJSON<VideoTaskStatus>(`/detect/video/${taskId}`)
}

export function stopVideoTask(taskId: string): Promise<{ status: string }> {
  return fetchJSON<{ status: string }>(`/detect/video/${taskId}/stop`)
}

export async function startRTSP(url: string, fastMode = false, skipFrames = 15): Promise<RTSPTaskResponse> {
  const form = new FormData()
  form.append('url', url)
  form.append('fast_mode', String(fastMode))
  form.append('skip_frames', String(skipFrames))
  const res = await fetch(`${BASE}/detect/rtsp`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`RTSP error: ${res.status}`)
  return res.json()
}

export function getRTSPTaskStatus(taskId: string): Promise<RTSPTaskStatus> {
  return fetchJSON<RTSPTaskStatus>(`/detect/rtsp/${taskId}`)
}

export function stopRTSPTask(taskId: string): Promise<{ status: string }> {
  return fetchJSON<{ status: string }>(`/detect/rtsp/${taskId}/stop`)
}
