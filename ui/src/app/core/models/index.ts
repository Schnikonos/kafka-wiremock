// Data models for UI components

// ─── Load Testing ────────────────────────────────────────────────────────────

export interface LoadPhase {
  type: 'ramp' | 'steady';
  duration_s: number;
  from_users: number;
  to_users: number;
  model?: 'closed';
}

export interface LoadScenarioRequest {
  name: string;
  test_ids: string[];
  phases: LoadPhase[];
  think_time_ms: number;
  bucket_s: number;
}

export interface LoadMetricBucket {
  t_s: number;
  ok: number;
  ko: number;
  active_users: number;
  mean_ms: number;
  p50_ms: number;
  p90_ms: number;
  p99_ms: number;
  max_ms: number;
}

export interface LoadTestSummary {
  test_id: string;
  total: number;
  ok: number;
  ko: number;
  mean_ms: number;
  p50_ms: number;
  p90_ms: number;
  p99_ms: number;
  max_ms: number;
  error_rate_pct: number;
}

export interface LoadReport {
  job_id: string;
  scenario_name: string;
  scenario?: any;
  status: 'COMPLETED' | 'CANCELLED' | 'FAILED';
  started_at: string;
  completed_at: string;
  total_duration_s: number;
  total_requests: number;
  total_ok: number;
  total_ko: number;
  error_rate_pct: number;
  mean_ms: number;
  p50_ms: number;
  p90_ms: number;
  p99_ms: number;
  max_ms: number;
  buckets: LoadMetricBucket[];
  summaries: LoadTestSummary[];
}

export interface LoadJobStatus {
  job_id: string;
  scenario_name: string;
  scenario?: any;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'CANCELLED' | 'FAILED';
  created_at: string;
  started_at?: string;
  active_users: number;
  progress_pct: number;
  elapsed_s: number;
  buckets: LoadMetricBucket[];
  error?: string;
}

// ─── Existing models below ───────────────────────────────────────────────────
export interface Test {
  test_id: string;
  priority: number;
  tags: string[];
  skip: boolean;
  timeout_ms: number;
  when_injections: number;
  then_expectations: number;
}

export interface Send {
  send_id: string;
  priority: number;
  tags: string[];
  skip: boolean;
  timeout_ms: number;
  injections: number;
  scripts: number;
}

export interface TestResult {
  test_id: string;
  status: 'PASSED' | 'FAILED' | 'SKIPPED' | 'TIMEOUT';
  elapsed_ms: number;
  errors?: string[];
}

export interface SendResult {
  send_id: string;
  status: 'COMPLETED' | 'FAILED' | 'SKIPPED';
  elapsed_ms: number;
  errors?: string[];
}

export interface BulkTestExecutionRequest {
  test_ids: string[];
  mode: 'parallel' | 'sequential';
  repeat: number;
  parallel_workers?: number;
  repeat_mode?: 'sequential-repeats' | 'interleaved-repeats';
  force_run?: boolean;  // Execute even if test.skip == true
}

export interface BulkSendExecutionRequest {
  send_ids: string[];
  mode: 'parallel' | 'sequential';
  repeat: number;
  parallel_workers?: number;
  repeat_mode?: 'sequential-repeats' | 'interleaved-repeats';
}

export interface BulkTestExecutionResult {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  mode: string;
  repeat: number;
  parallel_workers?: number;
  repeat_mode?: string;
  elapsed_ms: number;
  results: TestResult[];
}

export interface BulkSendExecutionResult {
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  mode: string;
  repeat: number;
  parallel_workers?: number;
  repeat_mode?: string;
  elapsed_ms: number;
  results: SendResult[];
}

export interface HealthStatus {
  status: string;
}

export interface ListsResponse<T> {
  total: number;
  items: T[];
}

export interface Rule {
  name: string;
  priority: number;
  input_destination: string;
  conditions: RuleCondition[];
  outputs: RuleOutput[];
  skip?: boolean;
}

export interface RuleCondition {
  type: string;
  expression?: string;
  value?: string;
  regex?: string;
  matched?: boolean;
}

export interface RuleOutput {
  destination: string;
  delay_ms?: number;
  headers?: Record<string, string>;
}

export interface Message {
  topic: string;
  partition: number;
  offset: number;
  key: string | null;
  value: any;
  headers: Record<string, string>;
  timestamp: number;
}

export interface InjectMessageRequest {
  message: any;
}

export interface InjectMessageResponse {
  message_id: string;
  topic: string;
  status: string;
}

