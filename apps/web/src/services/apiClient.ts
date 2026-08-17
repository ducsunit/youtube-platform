export const API_BASE = '/api';

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
      ? { 'Content-Type': 'application/json', ...init.headers }
      : init?.headers,
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
