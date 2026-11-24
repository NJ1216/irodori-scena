import { aiJobInputFailure } from "./api-input-errors";
import { ApiConnectionError, ApiError, apiFailureKind } from "./api-error";
function errorDetailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) => {
        if (!issue || typeof issue !== "object") return "";
        const entry = issue as { loc?: unknown; msg?: unknown };
        const location = Array.isArray(entry.loc) ? entry.loc.slice(1).join(" → ") : "";
        const message = typeof entry.msg === "string" ? entry.msg : "";
        return location && message ? `${location}: ${message}` : message;
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" / ");
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
function codedApiFailure(code: string | undefined, technicalDetail: string): string | null {
  const capabilityCodes = new Set(["tts_model_unsupported_voice_design", "tts_model_unsupported_combined_voice_design", "voice_design_sample_too_long", "voice_design_clip_too_long"]);
  if (code && capabilityCodes.has(code)) return technicalDetail;
  if (code && ["project_revision_conflict", "render_input_changed", "project_changed", "project_locked"].includes(code)) return technicalDetail;
  if (code === "operation_conflict") return technicalDetail === "詳細情報はありません。" ? "ほかの処理と重なりました。処理が終わってから、もう一度お試しください。" : technicalDetail;
  return null;
}
function gatewayApiFailure(path: string, technicalDetail: string): string {
  if (path.startsWith("/api/local-llm/")) return technicalDetail === "詳細情報はありません。" ? "oMLX実行基盤の処理を完了できませんでした。もう一度お試しください。" : technicalDetail;
  const summary = path === "/api/characters/profile-suggestion" ? "LLMがキャスト設定の提案を完了できませんでした。" : "AIまたは音声生成サービスがリクエストを完了できませんでした。";
  return technicalDetail === "詳細情報はありません。" ? `${summary} 設定ページを確認してください。` : `${summary} 詳細: ${technicalDetail}`;
}
function userFacingApiFailure(status: number, technicalDetail: string, path: string, code?: string): string {
  const coded = codedApiFailure(code, technicalDetail);
  if (coded) return coded;
  if (status === 422 && path.startsWith("/api/pronunciation-dictionary")) return technicalDetail;
  if (status === 400 || status === 422) return "入力内容を確認して、もう一度お試しください。";
  if (status === 401 || status === 403) return "接続設定またはAPIキーを確認してください。";
  if (status === 404) return "対象が見つかりません。画面を開き直して、もう一度お試しください。";
  if (status === 409) return "ほかの処理と重なりました。処理が終わってから、もう一度お試しください。";
  if (status === 413) return "選択したファイルが大きすぎます。ファイルサイズを確認してください。";
  if (status === 429) return "短時間に処理が集中しています。少し待ってから、もう一度お試しください。";
  if ([502, 503, 504].includes(status)) return gatewayApiFailure(path, technicalDetail);
  if (status >= 500) return "アプリ内の処理で問題が発生しました。もう一度試しても解決しない場合は、アプリを再起動してください。";
  return "処理を完了できませんでした。もう一度お試しください。";
}
export function serviceConnectionFailure(error: unknown): Error {
  console.error("[SCENA API] service connection failed", error);
  return new ApiConnectionError("アプリのサービスに接続できません。アプリを開き直して、もう一度お試しください。");
}
export function responseFailure(status: number, body: { detail?: unknown }, path: string, method = "GET"): Error {
  const technicalDetail = errorDetailMessage(body.detail, "詳細情報はありません。");
  const errorCode = body.detail && typeof body.detail === "object" && !Array.isArray(body.detail) ? (body.detail as { code?: unknown }).code : undefined;
  const logDetail = status >= 500 && /^\/api\/lines\/[^/]+\/(generate|regenerate)$/.test(path) ? "internal generation error" : technicalDetail;
  console.error(`[SCENA API] ${method} ${path} failed (${status}): ${logDetail}`);
  const inputFailure = path === "/api/ai/jobs" && status === 422 ? aiJobInputFailure(body.detail) : null;
  const code = typeof errorCode === "string" ? errorCode : undefined;
  return new ApiError(inputFailure ?? userFacingApiFailure(status, technicalDetail, path, code), status, body.detail, code, apiFailureKind(path, method, status, body.detail));
}
