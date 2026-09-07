export const API_BASE = '/api';

// Optional bearer token for a privately deployed API. It is deliberately not
// hard-coded; set it through the runtime bootstrap before the app starts.
export const API_AUTH_TOKEN = (globalThis as typeof globalThis & { __YT_API_TOKEN?: string }).__YT_API_TOKEN
  ?? (typeof import.meta !== 'undefined' ? (import.meta as ImportMeta & { env?: Record<string, string> }).env?.VITE_API_TOKEN : undefined);

export function authHeaders(): HeadersInit {
  return API_AUTH_TOKEN ? { Authorization: `Bearer ${API_AUTH_TOKEN}` } : {};
}

export function authenticatedUrl(url: string): string {
  // EventSource cannot set Authorization headers. Query-token auth is opt-in on
  // the server and should only be used over HTTPS/private deployments.
  if (!API_AUTH_TOKEN) return url;
  return `${url}${url.includes('?') ? '&' : '?'}api_token=${encodeURIComponent(API_AUTH_TOKEN)}`;
}


export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(API_BASE + path, {
    ...init,
    headers: init?.body
      ? { 'Content-Type': 'application/json', ...authHeaders(), ...init.headers }
      : { ...authHeaders(), ...init?.headers },
  });
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try {
      detail = await resp.json();
    } catch {
      /* body không phải JSON — giữ statusText */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}
