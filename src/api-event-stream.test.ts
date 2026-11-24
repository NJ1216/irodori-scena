import { afterEach, describe, expect, it, vi } from "vitest";
import { streamApiEvents } from "./api-runtime";

afterEach(() => vi.restoreAllMocks());

function streamResponse(text: string, cancel = vi.fn()) {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
    },
    cancel,
  });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body));
  return { body, cancel };
}

describe("progress stream ownership", () => {
  it("cancels a malformed stream and releases it before a replacement can start", async () => {
    const { body, cancel } = streamResponse('data: {"sequence":1}\n\ndata: broken\n\n');
    const onEvent = vi.fn();
    await expect(streamApiEvents("/api/ai/jobs/test/events", onEvent)).rejects.toBeInstanceOf(SyntaxError);
    expect(onEvent).toHaveBeenCalledExactlyOnceWith({ sequence: 1 });
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("preserves a consumer error even when stream cancellation fails", async () => {
    const cancel = vi.fn().mockRejectedValue(new Error("cleanup failed"));
    const { body } = streamResponse('data: {"sequence":1}\n\n', cancel);
    const failure = new Error("sequence gap");
    await expect(
      streamApiEvents("/api/ai/jobs/test/events", () => {
        throw failure;
      }),
    ).rejects.toBe(failure);
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("releases an aborted pending read and preserves the abort failure", async () => {
    let source!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        source = controller;
      },
    });
    const abort = new AbortController();
    const failure = new DOMException("cancelled", "AbortError");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      init?.signal?.addEventListener("abort", () => source.error(failure), { once: true });
      return new Response(body);
    });
    const onEvent = vi.fn();
    const pending = streamApiEvents("/api/ai/jobs/test/events", onEvent, { signal: abort.signal });
    await vi.waitFor(() => expect(body.locked).toBe(true));
    const rejection = expect(pending).rejects.toBe(failure);
    abort.abort();
    await rejection;
    expect(onEvent).not.toHaveBeenCalled();
    expect(body.locked).toBe(false);
  });

  it("keeps split UTF-8 progress frames and releases normal EOF without cancellation", async () => {
    const cancel = vi.fn();
    const bytes = new TextEncoder().encode(': keep-alive\n\ndata: {"phase":"生成中"}\n\ndata: {"terminal":true}\n\n');
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      },
      cancel,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body));
    const onEvent = vi.fn();
    await streamApiEvents("/api/ai/jobs/test/events", onEvent);
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([{ phase: "生成中" }, { terminal: true }]);
    expect(cancel).not.toHaveBeenCalled();
    expect(body.locked).toBe(false);
  });
});
