import { apiBaseUrl, apiFetch, rewriteApiUrls } from "./api-runtime";
import { responseFailure, serviceConnectionFailure } from "./api-failure";
export type HistoryScope = "script" | "characters" | "pronunciation";
export const HISTORY_CHANGED_EVENT = "scena:history-changed";
export const HISTORY_APPLIED_EVENT = "scena:history-applied";

async function responseJson<T>(response: Response, signal?: AbortSignal | null): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch (error) {
    // Fetch can succeed at the headers and disconnect while reading the body.
    // A malformed JSON document or an explicit abort is not a retryable transport failure.
    if (!signal?.aborted && (error instanceof TypeError || (error instanceof DOMException && error.name === "NetworkError"))) throw serviceConnectionFailure(error);
    throw error;
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let base: string;
  let response: Response;
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  try {
    base = await apiBaseUrl();
    response = await apiFetch(path, {
      // A project is modified by background jobs such as batch export. Never
      // allow a completed-line refresh to reuse an older project snapshot.
      cache: "no-store",
      ...init,
      headers,
    });
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw serviceConnectionFailure(error);
  }
  if (!response.ok) {
    const body = await response.json().catch(async () => ({ detail: await response.text().catch(() => "") }));
    throw responseFailure(response.status, body, path, init?.method);
  }
  const value = rewriteApiUrls(await responseJson<T>(response, init?.signal), base);
  const historyScope = response.headers?.get("X-SCENA-History-Scope") as HistoryScope | null;
  if (historyScope && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<HistoryScope>(HISTORY_CHANGED_EVENT, { detail: historyScope }));
  }
  return value;
}
export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("WAVファイルを読み込めませんでした。"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        return reject(new Error("WAVファイルを読み込めませんでした。"));
      }
      resolve(result.split(",", 2)[1] ?? "");
    };
    reader.readAsDataURL(file);
  });
}
