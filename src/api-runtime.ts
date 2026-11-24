// Tauri v2 exposes this marker as `window.isTauri`; __TAURI_INTERNALS__ is
// deliberately not a public/global API unless withGlobalTauri is enabled.
const isTauri = Boolean((globalThis as { isTauri?: boolean }).isTauri);
export const isDesktopRuntime = isTauri;
export type ApiConnection = { baseUrl: string; token: string };
let desktopConnection: Promise<ApiConnection> | null = null;

export async function apiConnection(): Promise<ApiConnection> {
  if (!isTauri) return { baseUrl: "", token: "" };
  desktopConnection ??= import("@tauri-apps/api/core").then(({ invoke }) => invoke<ApiConnection>("api_connection"));
  return desktopConnection;
}

export async function apiBaseUrl() {
  return (await apiConnection()).baseUrl;
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const connection = await apiConnection();
  const headers = new Headers(init.headers);
  if (connection.token) headers.set("Authorization", `Bearer ${connection.token}`);
  return fetch(/^https?:\/\//.test(path) ? path : `${connection.baseUrl}${path}`, { ...init, headers });
}

export async function streamApiEvents<T>(path: string, onEvent: (event: T) => void, options: { signal?: AbortSignal; lastEventId?: number } = {}) {
  const headers = new Headers({ Accept: "text/event-stream" });
  if (options.lastEventId) headers.set("Last-Event-ID", String(options.lastEventId));
  const response = await apiFetch(path, { cache: "no-store", headers, signal: options.signal });
  if (!response.ok || !response.body) throw new Error(`進捗ストリームへ接続できませんでした (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let ended = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      ended = done;
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (data) onEvent(JSON.parse(data) as T);
      }
      if (done) return;
    }
  } finally {
    try {
      if (!ended) await reader.cancel();
    } catch {
      // A failed/aborted body can also reject cancellation; retain the original error.
    } finally {
      reader.releaseLock();
    }
  }
}

export async function apiUrl(path: string) {
  return /^https?:\/\//.test(path) ? path : `${await apiBaseUrl()}${path}`;
}

export async function chooseProjectBackupDestination(defaultPath: string) {
  if (!isTauri) throw new Error("プロジェクトのバックアップはデスクトップアプリ専用です。");
  const { save } = await import("@tauri-apps/plugin-dialog");
  return save({
    defaultPath,
    filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }],
  });
}

export async function chooseProjectSaveDestination(defaultPath: string) {
  if (!isTauri) throw new Error("プロジェクトの保存はデスクトップアプリ専用です。");
  const { save } = await import("@tauri-apps/plugin-dialog");
  return save({ defaultPath, filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }] });
}

export async function chooseProjectFile() {
  if (!isTauri) throw new Error("プロジェクトを開く操作はデスクトップアプリ専用です。");
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({ directory: false, multiple: false, title: "開く .scena プロジェクトを選択", filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }] });
  return Array.isArray(selected) ? null : selected;
}

export async function downloadApiFile(path: string, fileName: string) {
  if (!isTauri) throw new Error("ダウンロードフォルダへの保存はデスクトップアプリ専用です。");
  const { invoke } = await import("@tauri-apps/api/core");
  const connection = await apiConnection();
  return invoke<string>("stream_api_download", {
    fileName,
    token: connection.token,
    url: await apiUrl(path),
  });
}

export async function saveLocalApiFile(localPath: string, fileName: string) {
  if (!isTauri) throw new Error("ローカルファイル保存はデスクトップアプリ専用です。");
  const { invoke } = await import("@tauri-apps/api/core");
  const { save } = await import("@tauri-apps/plugin-dialog");
  const destination = await save({ defaultPath: fileName });
  if (!destination) return false;
  await invoke("copy_local_file", { localPath, destination });
  return true;
}

export async function openExternal(url: string) {
  const scheme = new URL(url).protocol;
  if (scheme !== "http:" && scheme !== "https:") throw new Error("HTTP(S) のURLだけを開けます。");
  if (isTauri) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  } else window.open(url, "_blank", "noopener,noreferrer");
}

export async function defaultExportDirectory() {
  if (!isTauri) return "";
  const { desktopDir } = await import("@tauri-apps/api/path");
  return desktopDir();
}

export async function chooseDirectory(prompt: string, defaultPath?: string) {
  if (!isTauri) throw new Error("ローカルモデル設定はデスクトップアプリ専用です。");
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({ directory: true, multiple: false, title: prompt, defaultPath });
  return Array.isArray(selected) ? null : selected;
}

export async function chooseCastFiles() {
  if (!isTauri) throw new Error("キャストインポートはデスクトップアプリ専用です。");
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    directory: false,
    multiple: true,
    title: "読み込むキャストを選択",
    filters: [{ name: "irodori SCENA キャスト", extensions: ["scenacast"] }],
  });
  if (!selected) return [];
  return Array.isArray(selected) ? selected : [selected];
}

export function rewriteApiUrls<T>(value: T, base: string): T {
  if (!base || !value || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((entry) => rewriteApiUrls(entry, base)) as T;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, key.endsWith("Url") && typeof entry === "string" && entry.startsWith("/") ? `${base}${entry}` : rewriteApiUrls(entry, base)])) as T;
}
