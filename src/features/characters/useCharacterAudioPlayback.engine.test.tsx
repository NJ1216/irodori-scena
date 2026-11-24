import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { apiFetch } from "../../api-runtime";
import { useCharacterAudioPlayback } from "./useCharacterAudioPlayback";

vi.mock("../../api", () => ({ api: { clearCandidates: vi.fn().mockResolvedValue(undefined) } }));
vi.mock("../../api-runtime", () => ({ apiFetch: vi.fn() }));

afterEach(() => vi.unstubAllGlobals());

function closableContext() {
  const node = () => ({ connect: vi.fn(), channelCount: 0, channelCountMode: "max", channelInterpretation: "speakers", gain: { value: 0 } });
  const source = { buffer: null as unknown, onended: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn() };
  const context = {
    state: "running" as string,
    currentTime: 0,
    destination: {},
    close: vi.fn(async () => {
      context.state = "closed";
    }),
    resume: vi.fn(async () => undefined),
    decodeAudioData: vi.fn(async () => {
      if (context.state === "closed") throw new Error("context is closed");
      return { duration: 1 };
    }),
    createGain: vi.fn(node),
    createChannelSplitter: vi.fn(node),
    createChannelMerger: vi.fn(node),
    createAnalyser: vi.fn(() => ({ ...node(), fftSize: 0, getFloatTimeDomainData: vi.fn() })),
    createBufferSource: vi.fn(() => source),
  };
  return { context, source };
}

it("plays a cast reference even when the file arrives after the idle output would retire", async () => {
  const { context, source } = closableContext();
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function AudioContextMock() {
      return context;
    }),
  );
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.mocked(apiFetch).mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) } as never), 5)));
  const character = { id: "cast-1", name: "春", referenceAudioUrl: "/media/haru.wav", referenceVersion: 1 } as Character;
  const { result } = renderHook(() => useCharacterAudioPlayback());

  await act(() => result.current.playReferenceAudio(character));

  expect(context.close).not.toHaveBeenCalled();
  expect(source.start).toHaveBeenCalledOnce();
  expect(result.current.playingReferenceCharacterId).toBe("cast-1");
});
