import type { AssetsResponse, Result } from './types';

const rawBase = import.meta.env.VITE_API_BASE_URL ?? '';
const base = rawBase.endsWith('/') ? rawBase.slice(0, -1) : rawBase;

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string') return data.detail;
    return JSON.stringify(data?.detail ?? data);
  } catch {
    return await response.text();
  }
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

export async function predict(payload: any): Promise<Result> {
  return requestJson<Result>(`${base}/api/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function predictFile(form: FormData): Promise<Result> {
  return requestJson<Result>(`${base}/api/predict/file`, {
    method: 'POST',
    body: form,
  });
}

export async function updateData() {
  return requestJson(`${base}/api/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
}

export async function getAssets(): Promise<AssetsResponse> {
  return requestJson<AssetsResponse>(`${base}/api/assets`);
}
