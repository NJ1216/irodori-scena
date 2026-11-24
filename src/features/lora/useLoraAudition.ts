import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { request } from "../../api-core";
import type { Character, StudioProject } from "../../types";
import type { LoraMix } from "../../types/project";
import { DecodedAudioPlayer, type DecodedAudioPlaybackControl } from "../shared/decodedAudioPlayer";

type Job = { id: string; status: "generating" | "completed" | "cancelled" | "failed"; audioUrl?: string | null; error?: string | null };
export function auditionPayload(character: Character, mix: LoraMix, project: StudioProject) {
  const { quality, steps, textCfg, voiceCfg, captionCfg } = project.settings;
  return { characterId: character.id, referenceVersion: character.referenceVersion ?? 0, loraMix: mix, settings: { quality, steps, speechRate: 1, textCfg, voiceCfg, captionCfg: captionCfg ?? 3 } };
}
const cancelJob = (id: string) => request<Job>(`/api/lora/previews/${encodeURIComponent(id)}/cancel`, { method: "POST" });
export function useLoraAudition({ character, mix, project, onPlay }: { character: Character; mix: LoraMix; project: StudioProject; onPlay: (control: DecodedAudioPlaybackControl) => void }) {
  const [player] = useState(() => new DecodedAudioPlayer());
  const [generatingKey, setGeneratingKey] = useState("");
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [failure, setFailure] = useState({ key: "", text: "" });
  const lifecycle = useRef({ epoch: 0 });
  const jobId = useRef<string | null>(null);
  const cache = useRef<{ key: string; url: string } | null>(null);
  const payload = auditionPayload(character, mix, project);
  const key = JSON.stringify(["base-duration-rate1-v1", project.id, character.referenceAudioUrl, character.sampleText, project.ttsSelection, payload]);
  const currentKey = useRef(key);
  const playCallback = useRef(onPlay);
  useLayoutEffect(() => {
    currentKey.current = key;
    playCallback.current = onPlay;
  }, [key, onPlay]);
  useEffect(() => {
    player.setCallbacks({
      onDuration: setDuration,
      onTime: setCurrentTime,
      onPlay: (control) => {
        playCallback.current(control);
        setPlaying(true);
      },
      onPause: () => setPlaying(false),
      onEnded: () => setPlaying(false),
      onError: () => {
        setPlaying(false);
        cache.current = null;
        setFailure({ key: currentKey.current, text: "試聴音声を再生できませんでした。もう一度試聴してください。" });
      },
    });
    return () => player.dispose();
  }, [player]);
  useEffect(() => {
    const state = lifecycle.current;
    const changed = ++state.epoch;
    queueMicrotask(() => {
      if (state.epoch === changed) {
        setGeneratingKey("");
        setFailure({ key, text: "" });
      }
    });
    void player.setSource("");
    cache.current = null;
    if (jobId.current) void cancelJob(jobId.current).catch(() => {});
    jobId.current = null;
    return () => {
      state.epoch++;
      player.stop();
      if (jobId.current) void cancelJob(jobId.current).catch(() => {});
      jobId.current = null;
    };
  }, [key, player]);
  const generating = generatingKey === key;
  const error = failure.key === key ? failure.text : "";
  async function generate(active: () => boolean) {
    setGeneratingKey(key);
    let job = await request<Job>("/api/lora/previews", { method: "POST", body: JSON.stringify(payload) });
    if (!active()) {
      void cancelJob(job.id).catch(() => {});
      return null;
    }
    jobId.current = job.id;
    while (job.status === "generating" && active()) {
      await new Promise((resolve) => setTimeout(resolve, 300));
      if (!active()) return null;
      job = await request<Job>(`/api/lora/previews/${encodeURIComponent(job.id)}`);
    }
    if (!active()) return null;
    if (job.status !== "completed" || !job.audioUrl) throw new Error(job.error || "試聴をキャンセルしました。");
    cache.current = { key, url: job.audioUrl };
    return job.audioUrl;
  }
  async function playSource(url: string, active: () => boolean) {
    if (duration > 0 && cache.current?.url === url) await player.play();
    else if ((await player.setSource(url)) && active()) await player.play();
  }
  async function toggle() {
    if (generating) {
      lifecycle.current.epoch++;
      setGeneratingKey("");
      if (jobId.current) void cancelJob(jobId.current).catch((cause) => setFailure({ key, text: String(cause) }));
      jobId.current = null;
      return;
    }
    if (playing) {
      player.stop();
      return;
    }
    setFailure({ key, text: "" });
    const token = ++lifecycle.current.epoch;
    const active = () => lifecycle.current.epoch === token && currentKey.current === key;
    try {
      let url = cache.current?.key === key ? cache.current.url : null;
      if (!url) url = await generate(active);
      if (!url || !active()) return;
      setGeneratingKey("");
      // Stop reference playback before decoding too, then join the existing arbiter.
      playCallback.current(player);
      await playSource(url, active);
    } catch (cause) {
      if (active()) {
        setGeneratingKey("");
        setFailure({ key, text: (cause as Error).message });
        if (jobId.current) void cancelJob(jobId.current).catch(() => {});
      }
    }
  }
  return { generating, playing, error, toggle, duration, currentTime, seek: (seconds: number) => player.seek(seconds) };
}
