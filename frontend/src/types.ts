export interface Stats {
  total_detections: number
  unique_plates: number
  total_sessions: number
  avg_confidence: number | null
  detections_7d: number
  sessions_7d: number
}

export interface Detection {
  id: number
  timestamp: string
  source_type: string
  source_file: string | null
  plate_dtrb: string
  plate_persian: string | null
  confidence: number
}

export interface DetectionsResponse {
  data: Detection[]
  total: number
  limit: number
  offset: number
}

export interface TimelineEntry {
  dt: string
  cnt: number
}

export interface SourceEntry {
  source_type: string
  cnt: number
}

export interface ConfidenceEntry {
  bin: number
  cnt: number
}

export interface LetterEntry {
  plate_persian: string
  cnt: number
}

export interface Session {
  id: number
  source_type: string
  source_file: string | null
  started_at: string
  ended_at: string | null
  total_frames: number
  total_plates: number
  unique_plates: number
  status: string
}

export interface GetDetectionsParams {
  limit?: number
  offset?: number
  source_type?: string
  search?: string
}

export interface PlateResult {
  plate_dtrb: string
  plate_persian: string
  confidence: number
  bbox: [number, number, number, number]
}

export interface DetectImageResponse {
  session_id: number
  annotated: string
  plates: PlateResult[]
}

export interface VideoTaskResponse {
  task_id: string
  session_id: number
}

export interface VideoTaskStatus {
  status: string
  frame_idx: number
  total_frames: number
  plate_log: Array<{
    frame: number
    time: string
    plate_text: string
    dtrb_text: string
    confidence: number
  }>
  live_detections: string[]
  error?: string
  output_path?: string
}

export interface RTSPTaskResponse {
  task_id: string
  session_id: number
}

export interface RTSPTaskStatus {
  status: string
  history: Array<{
    dtrb_text: string
    yolo_text: string
    confidence: number
    first_seen: string
    last_seen: string
    count: number
  }>
  live_detections: string[]
  annotated?: string
}
