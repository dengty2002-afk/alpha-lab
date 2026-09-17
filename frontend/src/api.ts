import type { Bootstrap, Entity, Health, Job, JsonObject, Report } from './types';
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const message = await response.text();
    let detail = message;
    try {
      const parsed = JSON.parse(message);
      detail = parsed.message || parsed.error || message;
    } catch {
      /* plain error */
    }
    throw new Error(`${response.status} · ${detail || response.statusText}`);
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : ({} as T);
}
export const api = {
  bootstrap: () => request<Bootstrap>('/bootstrap'),
  health: () => request<Health>('/health'),
  jobs: () => request<Job[]>('/jobs'),
  job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  logs: (id: string) => request<JsonObject[]>(`/jobs/${encodeURIComponent(id)}/logs`),
  result: (id: string) => request<Report>(`/jobs/${encodeURIComponent(id)}/result`),
  start: (type: string, config: JsonObject) =>
    request<Job>('/jobs', { method: 'POST', body: JSON.stringify({ type, config }) }),
  cancel: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  rerun: (id: string) =>
    request<Job>(`/jobs/${encodeURIComponent(id)}/rerun`, { method: 'POST', body: '{}' }),
  create: (kind: string, data: JsonObject) =>
    request<Entity>(`/entities/${kind}`, { method: 'POST', body: JSON.stringify(data) }),
  upload: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<{ path: string; name: string }>('/uploads', { method: 'POST', body });
  },
};
export function artifactUrl(id: string, name: string) {
  return `/api/jobs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}`;
}
