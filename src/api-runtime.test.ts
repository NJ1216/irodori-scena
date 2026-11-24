import { afterEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
const open = vi.fn();
const save = vi.fn();
const desktopDir = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/path", () => ({ desktopDir }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open, save }));
vi.mock("@tauri-apps/plugin-opener", () => ({ openUrl: vi.fn() }));

describe("desktop WAV export", () => {
  afterEach(() => {
    delete (globalThis as { isTauri?: boolean }).isTauri;
    vi.resetModules();
    vi.clearAllMocks();
  });

  it("opens a .scena-filtered backup save panel and preserves cancellation", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    save.mockResolvedValue(null);
    const { chooseProjectBackupDestination } = await import("./api-runtime");

    await expect(chooseProjectBackupDestination("作品.scena")).resolves.toBeNull();
    expect(save).toHaveBeenCalledWith({
      defaultPath: "作品.scena",
      filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }],
    });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("uses file dialogs for saving and opening .scena projects", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    save.mockResolvedValue("/tmp/作品.scena");
    open.mockResolvedValue("/tmp/作品.scena");
    const { chooseProjectFile, chooseProjectSaveDestination } = await import("./api-runtime");

    await expect(chooseProjectSaveDestination("作品.scena")).resolves.toBe("/tmp/作品.scena");
    await expect(chooseProjectFile()).resolves.toBe("/tmp/作品.scena");
    expect(save).toHaveBeenCalledWith({
      defaultPath: "作品.scena",
      filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }],
    });
    expect(open).toHaveBeenCalledWith(
      expect.objectContaining({
        directory: false,
        multiple: false,
        filters: [{ name: "irodori SCENA プロジェクト", extensions: ["scena"] }],
      }),
    );
  });

  it("resolves the operating system desktop as the default export directory", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    desktopDir.mockResolvedValue("C:\\Users\\test\\Desktop\\");
    const { defaultExportDirectory } = await import("./api-runtime");

    await expect(defaultExportDirectory()).resolves.toBe("C:\\Users\\test\\Desktop\\");
    expect(desktopDir).toHaveBeenCalledOnce();
  });

  it("does not offer project backup in a standalone browser", async () => {
    const { chooseProjectBackupDestination } = await import("./api-runtime");
    await expect(chooseProjectBackupDestination("作品.scena")).rejects.toThrow("デスクトップアプリ専用");
    expect(save).not.toHaveBeenCalled();
  });

  it("copies a joined WAV by local path without fetching audio", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    invoke.mockResolvedValue(undefined);
    save.mockResolvedValue(null);
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { saveLocalApiFile } = await import("./api-runtime");

    await expect(saveLocalApiFile("/tmp/joined.wav", "作品.wav")).resolves.toBe(false);
    expect(invoke).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("saves a Take WAV directly into the desktop download directory", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    invoke.mockResolvedValueOnce({ baseUrl: "http://127.0.0.1:49152", token: "secret" }).mockResolvedValueOnce("001_台詞 (2).wav");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { downloadApiFile } = await import("./api-runtime");

    await expect(downloadApiFile("http://127.0.0.1:49152/media/take.wav", "001_台詞.wav")).resolves.toBe("001_台詞 (2).wav");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenLastCalledWith("stream_api_download", {
      fileName: "001_台詞.wav",
      token: "secret",
      url: "http://127.0.0.1:49152/media/take.wav",
    });
  });

  it("gets one desktop connection and authenticates API requests", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    invoke.mockResolvedValue({ baseUrl: "http://127.0.0.1:49152", token: "secret" });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    const { apiFetch } = await import("./api-runtime");
    await apiFetch("/api/health");
    await apiFetch("/api/project");
    expect(invoke).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledWith("api_connection");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization")).toBe("Bearer secret");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://127.0.0.1:49152/api/health");
  });

  it("normalizes a non-Error desktop connection rejection", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    invoke.mockRejectedValue("API sidecar is unavailable");
    const { request } = await import("./api-core");

    const failure = await request("/api/settings/engine-directory").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toBeTruthy();
    expect((failure as Error).message).not.toBe("undefined");
  });

  it("parses authenticated SSE frames and sends the replay cursor", async () => {
    (globalThis as { isTauri?: boolean }).isTauri = true;
    invoke.mockResolvedValue({ baseUrl: "http://127.0.0.1:49152", token: "secret" });
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(': keep-alive\n\nid: 8\nevent: progress\ndata: {"sequence":8}\n\n'));
        controller.close();
      },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body, { status: 200 }));
    const { streamApiEvents } = await import("./api-runtime");
    const events: Array<{ sequence: number }> = [];
    await streamApiEvents<{ sequence: number }>("/api/ai/jobs/job/events", (event) => events.push(event), {
      lastEventId: 7,
    });
    expect(events).toEqual([{ sequence: 8 }]);
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret");
    expect(headers.get("Last-Event-ID")).toBe("7");
  });
});
