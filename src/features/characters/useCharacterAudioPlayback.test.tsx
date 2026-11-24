import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { apiFetch } from "../../api-runtime";
import { audioEngine } from "../shared/audioEngine";
import { useCharacterAudioPlayback } from "./useCharacterAudioPlayback";

vi.mock("../../api", () => ({ api: { clearCandidates: vi.fn().mockResolvedValue(undefined) } }));
vi.mock("../../api-runtime", () => ({ apiFetch: vi.fn() }));
vi.mock("../shared/audioEngine", () => ({
  audioEngine: { createBufferSource: vi.fn(), decodeAudioData: vi.fn(), setBufferPlaybackActive: vi.fn() },
}));

const character = { id: "cast-1", name: "春", referenceAudioUrl: "/media/haru.wav", referenceVersion: 4 } as Character;

beforeEach(() => vi.clearAllMocks());

it("stops the previous decoded Voice Design candidate before another starts", () => {
  const first = { stop: vi.fn() };
  const second = { stop: vi.fn() };
  const { result } = renderHook(() => useCharacterAudioPlayback());

  act(() => result.current.beginCandidatePlayback(first));
  act(() => result.current.beginCandidatePlayback(second));

  expect(first.stop).toHaveBeenCalledOnce();
  expect(second.stop).not.toHaveBeenCalled();
  expect(result.current.activeCandidateAudio.current).toBe(second);
});

it("decodes the complete reference WAV before scheduling it from sample zero", async () => {
  const source = { buffer: null, onended: null, start: vi.fn(), stop: vi.fn() };
  const buffer = { duration: 1.5 };
  const context = { currentTime: 3 };
  vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
  vi.mocked(audioEngine.createBufferSource).mockResolvedValue({ context, source } as never);
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } as never);
  const { result } = renderHook(() => useCharacterAudioPlayback());

  await act(() => result.current.playReferenceAudio(character));

  expect(apiFetch).toHaveBeenCalledWith("/media/haru.wav?v=4", { cache: "force-cache" });
  expect(audioEngine.decodeAudioData).toHaveBeenCalledOnce();
  expect(source.buffer).toBe(buffer);
  expect(source.start).toHaveBeenCalledWith(3.02, 0);
  expect(audioEngine.setBufferPlaybackActive).toHaveBeenCalledWith(true);
});
