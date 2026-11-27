import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api-runtime";
import { audioEngine } from "./audioEngine";
import { DecodedAudioPlayer } from "./decodedAudioPlayer";

vi.mock("../../api-runtime", () => ({ apiFetch: vi.fn() }));
vi.mock("./audioEngine", () => ({
  audioEngine: {
    createBufferSource: vi.fn(),
    decodeAudioData: vi.fn(),
    setBufferPlaybackActive: vi.fn(),
  },
}));

function createSource() {
  return { buffer: null, disconnect: vi.fn(), onended: null, start: vi.fn(), stop: vi.fn() };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

describe("DecodedAudioPlayer", () => {
  it("fetches and decodes the complete WAV before scheduling sample zero", async () => {
    const bytes = new ArrayBuffer(12);
    const buffer = { duration: 1.5 };
    const context = { currentTime: 4 };
    const source = createSource();
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(bytes) } as never);
    vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
    vi.mocked(audioEngine.createBufferSource).mockResolvedValue({ context, source } as never);
    const player = new DecodedAudioPlayer();

    await player.setSource("/media/candidate.wav");
    await player.play();

    expect(apiFetch).toHaveBeenCalledWith("/media/candidate.wav", { cache: "force-cache" });
    expect(audioEngine.decodeAudioData).toHaveBeenCalledWith(bytes);
    expect(source.buffer).toBe(buffer);
    expect(source.start).toHaveBeenCalledWith(4.02, 0);
    expect(audioEngine.setBufferPlaybackActive).toHaveBeenCalledWith(true);
  });

  it("restarts a playing decoded buffer at the requested seek position", async () => {
    const buffer = { duration: 2 };
    const context = { currentTime: 8 };
    const first = createSource();
    const second = createSource();
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } as never);
    vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
    vi.mocked(audioEngine.createBufferSource)
      .mockResolvedValueOnce({ context, source: first } as never)
      .mockResolvedValueOnce({ context, source: second } as never);
    const player = new DecodedAudioPlayer();
    await player.setSource("/media/reference.wav");
    await player.play();

    player.seek(0.4);
    await vi.waitFor(() => expect(second.start).toHaveBeenCalled());

    expect(first.stop).toHaveBeenCalledOnce();
    expect(second.start).toHaveBeenCalledWith(8.02, 0.4);
    expect(vi.mocked(audioEngine.setBufferPlaybackActive).mock.calls).toEqual([[true], [false], [true]]);
  });

  it("clears the shared meter and reports natural completion", async () => {
    const buffer = { duration: 1 };
    const context = { currentTime: 2 };
    const source = createSource();
    const onEnded = vi.fn();
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } as never);
    vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
    vi.mocked(audioEngine.createBufferSource).mockResolvedValue({ context, source } as never);
    const player = new DecodedAudioPlayer({ onEnded });
    await player.setSource("/media/reference.wav");
    await player.play();

    (source.onended as (() => void) | null)?.();

    expect(vi.mocked(audioEngine.setBufferPlaybackActive).mock.calls).toEqual([[true], [false]]);
    expect(onEnded).toHaveBeenCalledWith(player);
  });

  it("starts only the latest source when play requests overlap and stop silences it", async () => {
    const buffer = { duration: 2 };
    const context = { currentTime: 1 };
    const stale = createSource();
    const latest = createSource();
    let resolveStale!: (value: unknown) => void;
    let resolveLatest!: (value: unknown) => void;
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } as never);
    vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
    vi.mocked(audioEngine.createBufferSource)
      .mockReturnValueOnce(new Promise((resolve) => (resolveStale = resolve)) as never)
      .mockReturnValueOnce(new Promise((resolve) => (resolveLatest = resolve)) as never);
    const player = new DecodedAudioPlayer();
    await player.setSource("/media/reference.wav");

    const first = player.play();
    await vi.waitFor(() => expect(audioEngine.createBufferSource).toHaveBeenCalledTimes(1));
    player.pause();
    const second = player.play();
    await vi.waitFor(() => expect(audioEngine.createBufferSource).toHaveBeenCalledTimes(2));
    resolveStale({ context, source: stale });
    resolveLatest({ context, source: latest });
    await Promise.all([first, second]);

    expect(stale.start).not.toHaveBeenCalled();
    expect(stale.disconnect).toHaveBeenCalled();
    expect(latest.start).toHaveBeenCalledOnce();
    player.stop();
    expect(latest.stop).toHaveBeenCalled();
  });

  it("replays from sample zero after natural completion", async () => {
    const buffer = { duration: 1 };
    const context = { currentTime: 2 };
    const first = createSource();
    const second = createSource();
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } as never);
    vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
    vi.mocked(audioEngine.createBufferSource)
      .mockResolvedValueOnce({ context, source: first } as never)
      .mockResolvedValueOnce({ context, source: second } as never);
    const player = new DecodedAudioPlayer();
    await player.setSource("/media/reference.wav");
    await player.play();
    (first.onended as (() => void) | null)?.();

    await player.play();

    expect(second.start).toHaveBeenCalledWith(2.02, 0);
  });
});
it("clears an old reference without fetching an empty URL or playing the old buffer", async () => {
  const context = { currentTime: 4 };
  const buffer = { duration: 1 };
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(12)) } as never);
  vi.mocked(audioEngine.decodeAudioData).mockResolvedValue({ context, buffer } as never);
  const player = new DecodedAudioPlayer();
  await player.setSource("/old.wav");
  expect(await player.setSource("")).toBe(false);
  await player.play();
  expect(apiFetch).toHaveBeenCalledTimes(1);
  expect(audioEngine.createBufferSource).not.toHaveBeenCalled();
});
