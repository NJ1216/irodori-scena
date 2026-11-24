import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { request } from "./api-core";

describe("project API contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("requests a cache-busted project snapshot without browser caching", async () => {
    const project = { version: 1, id: "project-test", title: "Contract" };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => project,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.project()).resolves.toEqual(project);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toMatch(/^\/api\/project\?refresh=\d+$/);
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(options.cache).toBe("no-store");
    expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
  });

  it("keeps API error details out of the user-facing message", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: "Project needs scenes and characters arrays.",
        }),
      }),
    );

    await expect(api.project()).rejects.toThrow("入力内容を確認して、もう一度お試しください。");
    expect(consoleError).toHaveBeenCalledWith(expect.stringContaining("Project needs scenes and characters arrays."));
  });

  it("keeps validation field names in diagnostics only", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [{ loc: ["body", "character_ids"], msg: "List should have at most 6 items" }],
        }),
      }),
    );

    await expect(api.project()).rejects.toThrow("入力内容を確認して、もう一度お試しください。");
    expect(consoleError).toHaveBeenCalledWith(expect.stringContaining("character_ids: List should have at most 6 items"));
  });

  it("shows a resolved internal API failure as an application processing error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({
          detail: { code: "internal_server_error", message: "アプリ内部の処理エラーが発生しました。" },
        }),
      }),
    );

    await expect(api.candidates("声", 1, "こんにちは。")).rejects.toThrow("アプリ内の処理で問題が発生しました。");
  });
});

describe("project API service failures and uploads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses the connection error only when fetch rejects", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(api.candidates("声", 1, "こんにちは。")).rejects.toThrow("アプリのサービスに接続できません。");
  });

  it("preserves intentional cancellation without reporting a service failure", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(controller.signal.reason));
    await expect(request("/api/timeline/plan", { signal: controller.signal })).rejects.toBe(controller.signal.reason);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("includes service error details in gateway failure messages", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({
          detail: "LLM error 404: model 'another-model' not found",
        }),
      }),
    );

    await expect(api.project()).rejects.toThrow("AIまたは音声生成サービスがリクエストを完了できませんでした。 詳細: LLM error 404: model 'another-model' not found");
    expect(consoleError).toHaveBeenCalledWith(expect.stringContaining("LLM error 404: model 'another-model' not found"));
  });

  it("shows an oMLX gateway failure without the unrelated AI service prefix", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({ detail: "Releaseを検証できませんでした: HTTP Error 404: Not Found" }),
      }),
    );

    await expect(api.installOmlxRuntimeVersion("v0.6.3")).rejects.toThrow("Releaseを検証できませんでした: HTTP Error 404: Not Found");
  });

  it("describes character profile suggestion failures as LLM failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({
          detail: "LLMから利用できるキャスト設定の提案を受け取れませんでした。",
        }),
      }),
    );

    await expect(
      api.suggestCharacterProfile({
        name: "話者A",
        profile: "",
        profile_details: {},
        idea: "",
        other_casts: [],
      }),
    ).rejects.toThrow("LLMがキャスト設定の提案を完了できませんでした。");
  });

  it("sends emotion metadata when importing a Voice Design reference", async () => {
    const candidate = { id: "emotion-reference", kind: "emotion", emotion: "joy", referenceCandidateId: "baseline-1" };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ candidate }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.importVoiceDesignReference(new File(["RIFF0000WAVEdata"], "joy.wav", { type: "audio/wav" }), {
      kind: "emotion",
      emotion: "joy",
      referenceCandidateId: "baseline-1",
    });

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      kind: "emotion",
      emotion: "joy",
      reference_candidate_id: "baseline-1",
    });
  });
});

describe("pronunciation dictionary API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the specific validation reason", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: "同じ語句は手動辞書に一件だけ登録できます。" }),
      }),
    );

    await expect(api.changePronunciationDictionary({ operation: "add-manual", term: "再生成", reading: "さい・せいせい" })).rejects.toThrow("同じ語句は手動辞書に一件だけ登録できます。");
  });
});

describe("coded TTS API failures", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([
    [422, "tts_model_unsupported_voice_design", "選択中の音声モデルはVoiceDesignに対応していません。音声モデルを切り替えてください。"],
    [409, "operation_conflict", "Irodori-TTSの音声合成を実行中です。完了または停止後に再試行してください。"],
    [409, "project_locked", "このプロジェクトは別のSCENAで編集中です。別のSCENAを閉じてから、もう一度開いてください。"],
  ])("shows the specific reason for HTTP %i", async (status, code, message) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status,
        json: async () => ({ detail: { code, message } }),
      }),
    );

    await expect(api.candidates("声", 1, "こんにちは。")).rejects.toThrow(message);
  });
});
