import { afterEach, expect, it, vi } from "vitest";
import { request } from "./api-core";
import { ApiConnectionError, ApiError } from "./api-error";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("distinguishes transport failures from application and JSON failures", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("network failed")).mockResolvedValueOnce(new Response("invalid JSON"));
  vi.stubGlobal("fetch", fetch);
  await expect(request("/api/project")).rejects.toBeInstanceOf(ApiConnectionError);
  await expect(request("/api/project")).rejects.toBeInstanceOf(SyntaxError);
});

it.each([
  ["/api/lines/line-1/generate", "POST", 409, "priority-interruption"],
  ["/api/project", "POST", 409, "priority-interruption"],
])("classifies only the existing generation interruption: %s %s %s", async (path, method, status, kind) => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const detail = { code: "priority_interruption", message: "優先再生のため自動生成を中断しました。" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail }, { status })),
  );
  const error = await request(path, { method }).catch((value: unknown) => value);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status, detail, code: detail.code, kind });
  expect((error as ApiError).message).not.toContain("優先再生");
});

it("does not infer priority interruption from a localized message", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const detail = "優先再生のため自動生成を中断しました。";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail }, { status: 409 })),
  );
  await expect(request("/api/lines/line-1/generate", { method: "POST" })).rejects.toMatchObject({ kind: "http", code: undefined });
});

it("retains the original coded detail and user-facing message", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const detail = { code: "operation_conflict", message: "処理中です。", currentRevision: 42 };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail }, { status: 409 })),
  );
  await expect(request("/api/project")).rejects.toMatchObject({ status: 409, detail, code: detail.code, kind: "http", message: detail.message });
});

it.each(["project_revision_conflict", "render_input_changed", "project_changed"])("shows the safe backend message for %s", async (code) => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const detail = { code, message: "安全な理由です。" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail }, { status: 409 })),
  );
  await expect(request("/api/lines/line-1/generate", { method: "POST" })).rejects.toMatchObject({ code, message: detail.message });
});

it("does not expose or log an internal generation failure detail", async () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail: "/secret/path API_KEY=hidden 台詞本文" }, { status: 500 })),
  );
  const error = await request("/api/lines/line-1/generate", { method: "POST" }).catch((value: unknown) => value);
  expect((error as Error).message).not.toMatch(/secret|API_KEY|台詞本文/);
  expect(logged.mock.calls.flat().join(" ")).not.toMatch(/secret|API_KEY|台詞本文/);
});

it.each(["voice_design_sample_too_long", "voice_design_clip_too_long"])("shows the VoiceDesign length message verbatim: %s", async (code) => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const detail = { code, message: "試聴台詞を短くしてから、もう一度お試しください。" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail }, { status: 422 })),
  );
  await expect(request("/api/characters/candidates", { method: "POST" })).rejects.toMatchObject({ status: 422, code, message: detail.message });
});
