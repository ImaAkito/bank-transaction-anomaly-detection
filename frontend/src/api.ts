import { getToken, UnauthorizedError } from "./auth";
import type {
  AlertHistoryRow,
  ClientDetail,
  ClientRow,
  DriftReport,
  Me,
  ModelEvent,
  ModelInfo,
  UserRow,
  Stats,
  Transaction,
  TransactionPage,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    window.dispatchEvent(new Event("unauthorized"));
    throw new UnauthorizedError("401: требуется вход");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* тело ответа не JSON */
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export interface TransactionFilters {
  risk: string[];
  status: string;
  client_id: string;
  search: string;
  min_score: number;
  category: string;
  only_flagged: boolean;
  sort: "received" | "timestamp" | "score";
  order: "asc" | "desc";
  limit: number;
  offset: number;
}

export const api = {
  transactions(filters: Partial<TransactionFilters>): Promise<TransactionPage> {
    const params = new URLSearchParams();
    (filters.risk ?? []).forEach((r) => params.append("risk", r));
    if (filters.status) params.append("status", filters.status);
    if (filters.client_id) params.set("client_id", filters.client_id);
    if (filters.search) params.set("search", filters.search);
    if (filters.min_score) params.set("min_score", String(filters.min_score));
    if (filters.category) params.set("category", filters.category);
    if (filters.only_flagged) params.set("only_flagged", "true");
    if (filters.sort) params.set("sort", filters.sort);
    if (filters.order) params.set("order", filters.order);
    params.set("limit", String(filters.limit ?? 50));
    params.set("offset", String(filters.offset ?? 0));
    return request(`/api/transactions?${params}`);
  },
  transaction: (id: string) => request<Transaction>(`/api/transactions/${encodeURIComponent(id)}`),
  me: () => request<Me>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<{ access_token: string; username: string; role: string }>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  users: () => request<UserRow[]>("/api/users"),
  createUser: (username: string, password: string, role: string) =>
    request<UserRow>("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, role }),
    }),
  updateUser: (username: string, patch: { active?: boolean; role?: string }) => {
    const params = new URLSearchParams();
    if (patch.active !== undefined) params.set("active", String(patch.active));
    if (patch.role) params.set("role", patch.role);
    return request<UserRow>(`/api/users/${encodeURIComponent(username)}?${params}`, { method: "PATCH" });
  },
  drift: () => request<DriftReport>("/api/model/drift"),
  modelEvents: () => request<ModelEvent[]>("/api/model/events?limit=20"),
  retrain: () => request<{ status: string }>("/api/model/retrain", { method: "POST" }),
  review: (id: string, status: string, reviewer: string, comment: string) =>
    request<Transaction>(`/api/transactions/${encodeURIComponent(id)}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, reviewer, comment: comment || null }),
    }),
  clients: (search = "", onlyFlagged = false) =>
    request<ClientRow[]>(`/api/clients?limit=100&search=${encodeURIComponent(search)}&only_flagged=${onlyFlagged}`),
  client: (id: string) => request<ClientDetail>(`/api/clients/${encodeURIComponent(id)}`),
  alerts: (clientId?: string) =>
    request<AlertHistoryRow[]>(`/api/alerts/history?limit=50${clientId ? `&client_id=${encodeURIComponent(clientId)}` : ""}`),
  stats: () => request<Stats>("/api/stats"),
  model: () => request<ModelInfo>("/api/model"),
};
