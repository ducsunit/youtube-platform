// Kiểu dữ liệu khớp với API server backend (youtube_pipeline/api/routes.py).

export type Lang = 'vi' | 'en';

export interface ActiveRun {
  run_id: string;
  status: string;
  orphaned: boolean;
}

export interface InputFileInfo {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export interface MinimaxProfile {
  provider: string;
  speed: number;
  pitch: number;
  volume: number;
  reference_cpm_min: number;
  reference_cpm_max: number;
  calibration_required: boolean;
}

export interface ServerConfig {
  backend_root: string;
  runs_dir: string;
  python_executable: string;
  input_files: InputFileInfo[];
  default_input_file: string;
  minimax_profile: MinimaxProfile;
  stage_order: string[];
  active_run: ActiveRun | null;
  busy: boolean;
  poll_interval_ms: number;
}

export type ModelProviderType = 'gemini' | 'openai_compatible';

export interface ModelProfileConfig {
  provider: ModelProviderType;
  model: string;
  base_url: string;
  api_key_env: string;
  api_key_configured: boolean;
  temperature: number;
  max_output_tokens: number | null;
}

export interface ModelConfig {
  version: number;
  profiles: Record<string, ModelProfileConfig>;
  role_profiles: Record<string, string>;
  roles: string[];
  provider_types: ModelProviderType[];
}

export type StageStatus = 'pending' | 'running' | 'passed' | 'failed';

export interface StageRecord {
  stage_name: string;
  stage_version: string;
  status: StageStatus;
  attempts: number;
  input_fingerprint: string;
  started_at: string | null;
  finished_at: string | null;
  artifacts: unknown[];
  metrics: Record<string, unknown>;
  warnings: unknown[];
  error: unknown;
}

export interface ArtifactRef {
  artifact_type?: string;
  path?: string;
  producer_stage?: string;
  qa_status?: string;
}

export interface StageCounts {
  total: number;
  passed: number;
  failed: number;
  pending: number;
  running: number;
}

export interface RunSummary {
  run_id: string;
  topic: string;
  profile: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  stage_counts: StageCounts;
  warnings: unknown[];
  errors: unknown[];
  has_manifest: boolean;
  timeline_status: string | null;
  executing: boolean;
}

export interface RunState {
  schema_version: number;
  run_id: string;
  profile: string;
  topic: string;
  status: string;
  created_at: string;
  updated_at: string;
  execution_started_at: string | null;
  execution_finished_at: string | null;
  execution_elapsed_seconds: number | null;
  total_started_at: string | null;
  total_finished_at: string | null;
  total_elapsed_seconds: number;
  config_snapshot: Record<string, unknown>;
  stage_records: Record<string, StageRecord>;
  artifact_index: Record<string, ArtifactRef>;
  warnings: unknown[];
  errors: unknown[];
}

export interface RunDetail {
  run_id: string;
  run_dir: string;
  state: RunState;
  manifest: Record<string, unknown> | null;
  active: boolean;
  orphaned: boolean;
}

export interface ModelCallDiagnostic {
  label: string;
  provider: string;
  model: string;
  temperature: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  status: string;
  error_type: string | null;
}

export interface RunDiagnostics {
  run_id: string;
  source: 'sqlite' | 'run_state';
  indexed: boolean;
  run_status: string;
  updated_at: string | null;
  routing_snapshot: Record<string, unknown> | null;
  stages: unknown[];
  model_calls: {
    total: number;
    succeeded: number;
    failed: number;
    duration_ms: number;
    calls: ModelCallDiagnostic[];
  };
}

export interface ActiveStage {
  index: number;
  name: string;
  status: string;
}

export interface RunStatus {
  run_id: string;
  status: string;
  active_stage: ActiveStage | null;
  stage_counts: StageCounts;
  updated_at: string | null;
  finished: boolean;
  executing: boolean;
  orphaned: boolean;
  execution_started_at: string | null;
  execution_finished_at: string | null;
  execution_elapsed_seconds: number | null;
  total_started_at: string | null;
  total_finished_at: string | null;
  total_elapsed_seconds: number;
}

export interface RunEvent extends RunStatus {
  state?: RunState;
}

export interface LogPage {
  /** run log: run_id; data job log: job_id (nên field này optional). */
  run_id?: string;
  offset: number;
  limit: number;
  total_lines: number;
  next_offset: number;
  eof: boolean;
  log_exists: boolean;
  lines: string[];
}

export interface ArtifactInfo {
  artifact_type: string | null;
  size_bytes: number;
  content_type: string;
  qa_status: string | null;
  producer_stage: string | null;
}

export type ArtifactTree = Record<string, Record<string, ArtifactInfo>>;

export interface NewRunBody {
  mode: 'demo' | 'production';
  input_file?: string;
  run_id?: string;
  output_dir?: string;
}

// ---- Kéo data YouTube (youtube_pipeline/api/data_routes.py) ----------------

export type DataJobKind = 'connect' | 'pull' | 'reporting';

export interface ActiveDataJob {
  id: string;
  kind: DataJobKind;
  started_at: string | null;
  log_path: string;
  orphaned: boolean;
}

export interface DataLastResult {
  file: string;
  generated_at: string | null;
  channel_id: string | null;
  video_count: number;
  analytics_window: { start: string; end: string } | null;
}

export interface DataStatus {
  available: boolean;
  pull_dir: string | null;
  python: string | null;
  connected: boolean;
  expires_at: string | null;
  scopes_ok: boolean;
  busy: boolean;
  active_job: ActiveDataJob | null;
  last_result: DataLastResult | null;
}

export interface DataJob {
  id: string;
  kind: DataJobKind | null;
  status: 'running' | 'complete' | 'failed';
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DataPullBody {
  mode: 'video_ids' | 'range' | 'all';
  video_ids?: string[];
  start_date?: string;
  end_date?: string;
  max_comments?: number;
  max_replies?: number;
  no_replies?: boolean;
  out_file?: string;
}

export interface DataReportingBody {
  action: 'setup' | 'sync';
  out_file?: string;
}

export interface DataJobStarted {
  job_id: string;
  kind: DataJobKind;
}

// ---- Dựng video (youtube_pipeline/api/build_routes.py) ---------------------

export type TimelineStatus = 'DRAFT_TIMING' | 'FINAL_TIMING' | null;

export interface BuildAudio {
  file: string;
  duration_seconds: number | null;
  measured_cpm: number | null;
}

export interface BuildImages {
  present: number;
  missing: string[];
}

export interface BuildLastReport {
  status: string | null;
  generated_at: string | null;
  next_step: string | null;
  error: string | null;
}

export interface BuildTool {
  build_video_script: string;
}

export interface BuildPackFiles {
  prompts_build: boolean;
  marks_tsv: boolean;
}

export interface BuildStatus {
  run_id: string;
  active_job: ActiveDataJob | null;
  busy: boolean;
  pipeline_ready: boolean;
  missing_artifacts: string[];
  timeline_status: TimelineStatus;
  audio: BuildAudio | null;
  audio_ready: boolean;
  sections_count: number | null;
  events_count: number | null;
  unique_images: number | null;
  images: BuildImages;
  images_ready: boolean;
  pack_ready: boolean;
  pack_files: BuildPackFiles;
  video_exists: boolean;
  video_ready: boolean;
  missing_reason: string | null;
  last_report: BuildLastReport | null;
  tool: BuildTool;
}

export interface BuildJob {
  id: string;
  run_id: string | null;
  status: 'running' | 'complete' | 'failed';
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface BuildStartBody {
  render?: boolean;
  motion?: boolean;
  animation?: string;
  transition?: number;
  resolution?: [number, number];
  dry_run?: boolean;
  subtitles?: boolean;
  logo_cleanup?: boolean;
  logo_mode?: 'delogo' | 'blur';
}

export interface BuildJobStarted {
  job_id: string;
  run_id: string;
  started_at: string;
}

// Style phụ đề CapCut — khớp SUB_DEFAULTS của build-video.py + sub-style.json.
export type SubFont = 'Hiragino Kaku Gothic Pro' | 'Hiragino Maru Gothic ProN' | 'Hiragino Mincho ProN' | 'Hiragino Sans';
export type SubPosition = 'bottom' | 'top' | 'middle';

export interface SubStyle {
  font: SubFont;
  fontsize: number;
  color: string;
  outline: number;
  outline_color: string;
  shadow: number;
  bold: boolean;
  position: SubPosition;
  margin_v: number;
}

export interface BuildImportMapping {
  img: string;
  file: string;
}

export interface BuildImportResult {
  ok: boolean;
  mapping: BuildImportMapping[];
  extra: number;
  output: string;
  error?: string;
}

// ---------------------------------------------- Veo image-to-video (/video-gen)

export interface VeoActiveJob {
  id: string;
  run_id: string | null;
  started_at: string | null;
  log_path: string;
  orphaned?: boolean;
}

export interface VeoStatus {
  available: boolean;
  has_api_key: boolean;
  sdk_ready: boolean;
  default_model: string;
  models: string[];
  active_job: VeoActiveJob | null;
  busy: boolean;
}

export interface VeoCandidate {
  index: string;
  name: string;
  motion: string;
  prompt: string;
  image_exists: boolean;
  image_path: string | null;
  clip_exists: boolean;
  clip_path: string | null;
  clip_size_bytes: number | null;
}

export interface VeoCandidates {
  run_id: string;
  prompts_file_exists: boolean;
  images_dir: string;
  clips_dir: string;
  candidates: VeoCandidate[];
  total: number;
  images_ready: number;
  clips_done: number;
  active_job: VeoActiveJob | null;
  busy: boolean;
}

export interface VeoGenerateBody {
  images: string[];
  model?: string;
  skip_existing?: boolean;
}

export interface VeoJobStarted {
  job_id: string;
  run_id: string;
  images: string[];
  model: string;
  started_at: string;
  log_path: string;
}

export interface VeoJob {
  id: string;
  run_id: string | null;
  status: 'running' | 'complete' | 'failed';
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImageStatus {
  available: boolean;
  has_api_key: boolean;
  sdk_ready: boolean;
  model: string;
  models: string[];
  sizes: string[];
  qualities: string[];
  active_job: { id: string; run_id?: string; status: string } | null;
  busy: boolean;
}

export interface ImageConfig {
  model: string;
  base_url: string;
  api_key_env: string;
  api_key_configured: boolean;
  default_size: string;
  default_quality: string;
  models: string[];
  sizes: string[];
  qualities: string[];
}

export interface ImagePrompt {
  image_id: string;
  prompt: string;
  exists: boolean;
  path: string | null;
  size_bytes: number | null;
}

export interface ImagePrompts {
  run_id: string;
  prompt_pack_exists: boolean;
  images_dir: string;
  total: number;
  generated: number;
  prompts: ImagePrompt[];
  active_job: { id: string; run_id?: string; status: string } | null;
  busy: boolean;
}

export interface ImageJob {
  id: string;
  run_id?: string;
  status: 'running' | 'complete' | 'failed';
  exit_code: number | null;
  started_at?: string;
  finished_at?: string;
}

export interface SrtStatus {
  sdk_ready: boolean;
  accurate_ready: boolean;
  models: string[];
  devices: string[];
  modes: string[];
  active_job: { id: string; run_id?: string; status: string } | null;
  busy: boolean;
}

export interface SrtInputs {
  run_id: string;
  script_exists: boolean;
  script_path: string | null;
  audio_exists: boolean;
  audio_path: string | null;
  audio_size_bytes: number | null;
  srt_exists: boolean;
  srt_path: string | null;
  active_job: { id: string; run_id?: string; status: string } | null;
  busy: boolean;
}

export interface SrtJob {
  id: string;
  run_id?: string;
  status: 'running' | 'complete' | 'failed';
  exit_code: number | null;
  output_path?: string;
}
