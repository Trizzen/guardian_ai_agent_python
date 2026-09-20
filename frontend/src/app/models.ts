export type Status = 'backlog' | 'ready' | 'active' | 'waiting' | 'completed';
export type Priority = 'low' | 'normal' | 'high' | 'critical';
export type TargetType = 'program' | 'project';
export type CheckInStatus = 'none' | 'requested' | 'awaiting_direction';
export type Assignee = 'king_trizzen' | 'jaza' | 'star_reborn';
export type PetPresenceName = 'jaza' | 'star';
export type ReportingWindow = 'today' | 'week' | 'month' | 'ytd' | 'all';

export interface Program {
  id: string;
  name: string;
  short_name: string;
  description: string;
  capabilities: string[];
  accent: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: Status;
  priority: Priority;
  current_focus: string;
  next_action: string;
  notes: string;
  human_check_in_required: boolean;
  repository_path: string | null;
  updated_at: string;
}

export interface WorkItem {
  id: string;
  title: string;
  description: string;
  target_type: TargetType;
  target_id: string;
  domain_program: string | null;
  priority: Priority;
  status: Status;
  next_action: string;
  notes: string;
  created_at: string;
  updated_at: string;
  human_check_in_required: boolean;
  human_check_in_status: CheckInStatus;
  execution_assignee: Assignee;
  execution_status: 'not_delegated' | 'prepared_for_star';
  scheduled_for: string | null;
  review_after: string | null;
  attention_at?: string;
  jira_key?: string | null;
}

export type CodingStoryStatus = 'to_do' | 'in_progress' | 'in_review' | 'done';

export interface CodingRepository {
  id: string;
  name: string;
  repository_path: string;
}

export interface CodexUsage {
  available: boolean;
  window_minutes: number;
  used_percent: number | null;
  remaining_percent: number | null;
  resets_at: string | null;
  message: string | null;
  source: string;
}

export type CodeCrawlerState = 'not_run' | 'running' | 'completed' | 'failed';

export interface CodeCrawlerRun {
  local_project_id: string;
  repository_name: string;
  repository_path: string;
  tool_name: 'CodeCrawler';
  jira_key: string | null;
  state: CodeCrawlerState;
  started_at: string | null;
  completed_at: string | null;
  exit_code: number | null;
  error_category: string | null;
  file_count: number | null;
  output_paths: string[];
}

export type JiraAttachmentStatus = 'not_materialized' | 'ready' | 'failed';

export interface JiraAttachment {
  attachment_id: string;
  filename: string;
  mime_type: string | null;
  size: number | null;
  author: string | null;
  created: string | null;
  selected: boolean;
  status: JiraAttachmentStatus;
  sha256: string | null;
  error: string | null;
}

export interface JiraAttachments {
  count: number;
  selected_count: number;
  limit: number;
  requires_selection: boolean;
  ready: boolean;
  message: string | null;
  attachments: JiraAttachment[];
}

export interface CodingStory {
  jira_key: string;
  summary: string;
  description: string;
  markdown_description: string;
  status: CodingStoryStatus;
  assignee: string | null;
  priority: string | null;
  sprint: string | null;
  issue_type: string | null;
  local_project_id: string | null;
  local_repository_path: string | null;
  codex_thread_id: string | null;
  execution_state: string;
  execution_surface: 'APP' | 'TERMINAL' | null;
  execution_profile: { model: string; reasoning_effort: string } | null;
  execution_prepared_at: string | null;
  execution_last_activity: string | null;
  execution_last_activity_at: string | null;
  codecrawler: CodeCrawlerRun | null;
  attachments: JiraAttachments;
}

export interface CodingBoard {
  available: boolean;
  project: { key: string; name: string };
  sprint: { id: number; name: string; state: string };
  statuses: { id: CodingStoryStatus; label: string }[];
  stories: CodingStory[];
  repositories: CodingRepository[];
  refreshed_at: string;
  bootstrapped?: { local_work_item_id: string; jira_key: string }[];
  codex_usage: CodexUsage;
}

export interface ContextEntry {
  id: string;
  target_type: TargetType;
  target_id: string;
  body: string;
  created_at: string;
  status?: CheckInStatus;
}

export interface Dashboard {
  identity: { name: string; role: string; message: string };
  metrics: {
    needs_my_attention: number;
    active_work: number;
    ready: number;
    waiting: number;
    completed_today: number;
    prepared_for_star: number;
  };
  needs_attention: WorkItem[];
  attention_projects: Project[];
  attention_check_ins: ContextEntry[];
  upcoming: WorkItem[];
  recent_notes: ContextEntry[];
  recent_check_ins: ContextEntry[];
}

export interface PetPresence {
  available: boolean;
  selected_pet: PetPresenceName | null;
  selected_avatar_id: string | null;
  display_name: string | null;
  message: string | null;
}

export interface ReportingOverview {
  guard_this_kingdom: { connected: boolean; message: string | null };
  luna: { ready: boolean; provider: string; model: string; message: string | null };
  target_user_scope: number;
  windows: ReportingWindow[];
  domains: { id: string; label: string }[];
  source_policy: string;
}

export interface ReportStats {
  scheduled_goals: number;
  completed_goals: number;
  failed_goals: number;
  live_goals: number;
  completion_rate: number;
  failure_rate: number;
  recorded_minutes: number;
  completed_minutes: number;
  average_completed_minutes: number;
  goal_type_minutes: Record<string, number>;
  behavior_distribution: { standard: number; sliding: number };
  garden_records: number;
  garden_events: number;
}

export interface ReportActivity {
  source: string;
  source_kind: string;
  source_id: string;
  occurred_at: string | null;
  due_at: string | null;
  title: string;
  note: string;
  category: string;
  minutes: number | null;
  status: string;
  behavior: string;
  classification: { domain: string; confidence: number; reason: string; rule: string };
}

export interface LunaInsight {
  report_id: string;
  report_version: string;
  prompt_version: string;
  summary: string;
  wins: string[];
  patterns: string[];
  risks_or_attention: string[];
  recommended_next_focus: string;
  questions_for_king_trizzen: string[];
  evidence_insufficient: boolean;
  classification_decisions: {
    source_id: string;
    domain: string;
    confidence: number;
    reason: string;
  }[];
  generated_at: string;
  provider: string;
  model: string;
  grounded: boolean;
  source_modified: boolean;
  usage: Record<string, number>;
  latency_ms: number;
}

export interface DomainReport {
  available: boolean;
  domain: string;
  domain_label: string;
  window: ReportingWindow;
  window_label?: string;
  window_bounds?: { start: string; end_exclusive: string; timezone: string; gtk_week_start: string };
  source: { guard_this_kingdom: boolean; mode: string; target_user_id: number; jaza_local_state?: boolean };
  stats: ReportStats;
  prior_window_stats?: ReportStats | null;
  trend?: Record<string, number> | null;
  gtk_parity_stats?: Record<string, number>;
  activity: ReportActivity[];
  overdue_activity: ReportActivity[];
  attention_signals: { code: string; severity: string; message: string; rule: string }[];
  planning_context: {
    source: string;
    source_role: string;
    active_projects?: { id: string; name: string; status: string; current_focus: string; next_action: string }[];
    work_items?: { id: string; title: string; status: string; next_action: string }[];
  };
  classification: {
    classified_count: number;
    unclassified_count: number;
    ambiguous_for_luna: ReportActivity[];
    rules_version?: string;
    statistics_scope?: string;
  };
  provenance: {
    record_count: number;
    generated_at: string;
    report_version: string;
    prompt_version?: string;
  };
  insight: LunaInsight | null;
  insight_cache?: { status: string; ttl_seconds: number };
  insight_error?: { code: string; message: string };
  error?: { code: string; message: string };
}

export interface SentinelSnapshot {
  dashboard: Dashboard;
  petPresence: PetPresence;
  programs: Program[];
  projects: Project[];
  workItems: WorkItem[];
  reporting: ReportingOverview;
}

export interface TargetSelection {
  type: TargetType;
  id: string;
}
