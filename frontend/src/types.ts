export type RiskLevel = "low" | "medium" | "high";
export type Status = "normal" | "needs_review" | "reviewed_normal" | "reviewed_suspicious";

export interface Reason {
  code: string;
  type: string;
  severity: number;
  value: unknown;
  text: string;
}

export interface Factor {
  feature: string;
  label: string;
  value: number;
  contribution: number;
  direction: "increases" | "decreases";
}

export interface Analysis {
  anomaly_score: number;
  risk_level: RiskLevel;
  status: Status;
  summary: string;
  deviation_types: string[];
  reasons: Reason[];
  factors: Factor[];
  features: Record<string, number>;
  model_version: string;
  model_kind: string;
  latency_ms: number;
  profile_updated: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  created_at: string;
}

export interface Transaction {
  transaction_id: string;
  client_id: string;
  timestamp: string;
  amount: number;
  currency: string;
  amount_base: number;
  category: string;
  channel: string;
  recipient_id: string | null;
  recipient_category: string | null;
  extra: Record<string, unknown> | null;
  simulation_label: boolean | null;
  simulation_anomaly_type: string | null;
  received_at: string;
  analysis: Analysis;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export interface ClientRow {
  client_id: string;
  transactions: number;
  flagged: number;
  last_seen: string | null;
  max_score: number;
}

export interface ClientProfile {
  transactions_in_profile: number;
  transactions_seen: number;
  median_amount: number | null;
  p90_amount: number | null;
  mean_amount_geometric: number | null;
  max_amount: number | null;
  typical_hours: number[];
  hour_counts: number[];
  weekday_counts: number[];
  categories: Record<string, number>;
  channels: Record<string, number>;
  currencies: Record<string, number>;
  recipient_categories: Record<string, number>;
  known_recipients: number;
  avg_transactions_per_day: number;
}

export interface ClientDetail {
  client_id: string;
  first_seen: string;
  last_seen: string;
  profile: ClientProfile;
  recent: Transaction[];
}

export interface AlertHistoryRow {
  id: number;
  transaction_id: string;
  client_id: string;
  event_type: string;
  risk_level: string;
  anomaly_score: number;
  status: string;
  actor: string | null;
  comment: string | null;
  created_at: string;
}

export interface SimulationCheck {
  labeled: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  true_negative: number;
  precision: number | null;
  recall: number | null;
}

export interface Stats {
  total_transactions: number;
  clients: number;
  by_risk: Record<RiskLevel, number>;
  by_status: Record<string, number>;
  flagged_share: number;
  transactions_last_minute: number;
  avg_latency_ms: number;
  simulation_check: SimulationCheck | null;
}

export interface Aggregate {
  mean: number;
  std: number;
}

export interface ModelInfo {
  model: {
    kind: string;
    version: string;
    trained_at: string;
    feature_names: string[];
    thresholds: { medium: number; high: number };
    params: Record<string, unknown>;
    metrics: { test?: Record<string, number>; train_rows?: number; test_rows?: number };
  };
  experiments: null | {
    seeds: number[];
    tuned_isolation_forest_params: Record<string, unknown>;
    models: Record<
      string,
      {
        supervised: boolean;
        roc_auc: Aggregate;
        pr_auc: Aggregate;
        val_threshold: Record<"precision" | "recall" | "f1", Aggregate>;
        label_free_threshold?: Record<"precision" | "recall" | "f1", Aggregate>;
      }
    >;
    ablation: Record<string, { n_features: number; roc_auc: Aggregate; pr_auc: Aggregate; f1: Aggregate }>;
  };
}

export type LiveEvent = { type: "transaction_analyzed" | "transaction_reviewed"; data: Transaction };
