export type LicenseEntry = { id: string; name: string; version: string; license: string; source: string; scope: string; status: string; texts: Array<{ name: string; sha256: string }> };
export type Notices = { applicationLicense: string; entries: LicenseEntry[]; texts: Record<string, string> };

export async function loadLicenseNotices(signal: AbortSignal): Promise<Notices> {
  const response = await fetch(`${import.meta.env.BASE_URL}third-party-licenses.json.gz`, { signal });
  if (!response.ok) throw new Error("License resource unavailable");
  const bytes = new Uint8Array(await response.arrayBuffer());
  signal.throwIfAborted();
  // A server may already have decoded Content-Encoding; bundled assets contain gzip bytes.
  const compressed = bytes[0] === 0x1f && bytes[1] === 0x8b;
  const body = new Response(bytes).body!;
  const text = await new Response(compressed ? body.pipeThrough(new DecompressionStream("gzip")) : body).text();
  signal.throwIfAborted();
  return JSON.parse(text) as Notices;
}

export const licenseScopeLabel = (scope: string) => ({ "build-and-application": "アプリ・ビルド用", "build-and-api": "ローカルAPI・ビルド用", "runtime-download": "実行時ダウンロード", "bundled-environment-manager": "環境管理ツール", "bundled-python-runtime": "Python実行環境" })[scope] ?? "関連ライブラリ";
