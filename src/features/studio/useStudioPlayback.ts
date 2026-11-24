import { wakeContinuousPlaybackWaiters } from "./continuousPlaybackWait";
import { createContinuousPlayback, createSelectedPlayback } from "./continuousPlaybackRunner";
import type { StudioProjectEditingActions } from "./useStudioProjectEditing";
import type { StudioState } from "./useStudioState";
import { DecodedAudioPlayer } from "../shared/decodedAudioPlayer";
import type { Character } from "../../types";

export type PlaybackModel = Pick<
  StudioState,
  | "project"
  | "projectRef"
  | "busyRef"
  | "autoGenerateEnabledRef"
  | "setNotice"
  | "setStatusNotice"
  | "busy"
  | "stopPlayback"
  | "activeAudio"
  | "resolveActivePlayback"
  | "playbackRun"
  | "continuousPlaybackWaiters"
  | "setContinuousPlayback"
  | "continuousPlayback"
  | "setFocusedLineId"
  | "focusedLineId"
  | "playingLineId"
  | "setPlayingLineId"
  | "playingReferenceCharacterId"
  | "setPlayingReferenceCharacterId"
  | "selectedLinePlaybackStopRun"
  | "selectedLinePlaybackPending"
  | "stopRef"
  | "runWithAutoRenderPriorityRef"
> &
  Pick<StudioProjectEditingActions, "isProjectPersistencePending" | "waitForProjectPersistence">;

export function useStudioPlayback(model: PlaybackModel) {
  const {
    setStatusNotice,
    busy,
    stopPlayback,
    activeAudio,
    resolveActivePlayback,
    playbackRun,
    continuousPlaybackWaiters,
    setContinuousPlayback,
    setFocusedLineId,
    playingLineId,
    setPlayingLineId,
    playingReferenceCharacterId,
    setPlayingReferenceCharacterId,
    selectedLinePlaybackStopRun,
    selectedLinePlaybackPending,
    stopRef,
  } = model;
  function cancelPlayback() {
    stopPlayback.current = true;
    playbackRun.current += 1;
    activeAudio.current?.stop();
    activeAudio.current = null;
    resolveActivePlayback.current?.();
    resolveActivePlayback.current = null;
    wakeContinuousPlaybackWaiters(continuousPlaybackWaiters);
    setPlayingLineId(null);
    setPlayingReferenceCharacterId(null);
    setContinuousPlayback(false);
  }

  function play(url: string, lineId?: string, referenceCharacterId?: string) {
    if (lineId && playingLineId === lineId && activeAudio.current) {
      stop();
      return;
    }

    cancelPlayback();
    const run = playbackRun.current + 1;
    playbackRun.current = run;
    stopPlayback.current = false;
    const audio = new DecodedAudioPlayer();
    const finish = () => {
      if (playbackRun.current !== run) return;
      if (activeAudio.current === audio) activeAudio.current = null;
      if (resolveActivePlayback.current === finish) {
        resolveActivePlayback.current = null;
      }
      if (lineId) {
        setPlayingLineId((current) => (current === lineId ? null : current));
      }
      if (referenceCharacterId) setPlayingReferenceCharacterId((current) => (current === referenceCharacterId ? null : current));
    };
    activeAudio.current = audio;
    resolveActivePlayback.current = finish;
    if (lineId) {
      setFocusedLineId(lineId);
      setPlayingLineId(lineId);
      setStatusNotice("選択テイクを再生しています。");
    }
    if (referenceCharacterId) setPlayingReferenceCharacterId(referenceCharacterId);
    audio.setCallbacks({ onEnded: finish, onError: finish });
    void audio.setSource(url).then(() => {
      if (playbackRun.current === run) void audio.play();
    });
  }

  function playReference(character: Character) {
    if (playingReferenceCharacterId === character.id && activeAudio.current) {
      stop();
      return;
    }
    const separator = character.referenceAudioUrl.includes("?") ? "&" : "?";
    play(`${character.referenceAudioUrl}${separator}v=${character.referenceVersion ?? 0}`, undefined, character.id);
  }

  const startContinuousPlayback = createContinuousPlayback(model);
  async function playContinuous() {
    if (model.continuousPlayback) return;
    selectedLinePlaybackStopRun.current += 1;
    selectedLinePlaybackPending.current = false;
    cancelPlayback();
    const waitingRun = playbackRun.current;
    if (model.isProjectPersistencePending()) {
      setStatusNotice("変更を保存しています。完了後に連続再生を開始します。");
    }
    const ready = await model.waitForProjectPersistence();
    if (!ready || playbackRun.current !== waitingRun) return;
    await startContinuousPlayback();
  }

  async function playSelectedLines(lineIds: string[]) {
    if (!lineIds.length) return;
    cancelPlayback();
    await createSelectedPlayback(model, lineIds)();
  }

  function stop() {
    selectedLinePlaybackStopRun.current += 1;
    selectedLinePlaybackPending.current = false;
    cancelPlayback();
    setStatusNotice(busy === "export" ? "再生を停止しました。エクスポートは続行しています。" : "再生を停止しました。実行中の推論は安全に完了します。");
  }

  stopRef.current = stop;

  return { cancelPlayback, play, playReference, playContinuous, playSelectedLines, stop };
}

export type StudioPlaybackActions = ReturnType<typeof useStudioPlayback>;
