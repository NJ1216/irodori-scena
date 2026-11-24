import type { PlaybackModel } from "./useStudioPlayback";
import { runTimelineSession } from "./timelinePlaybackSession";

function createPlayback(model: PlaybackModel, selectedLineIds?: string[]) {
  return async function playContinuous() {
    const project = model.projectRef.current ?? model.project;
    if (!project || (model.continuousPlayback && !selectedLineIds)) return;
    if (model.busy === "draft") {
      model.setNotice("AI台本の生成中は、連続再生を開始できません。");
      return;
    }
    const run = ++model.playbackRun.current;
    model.stopPlayback.current = false;
    model.setContinuousPlayback(true);
    const stopped = () => model.stopPlayback.current || model.playbackRun.current !== run;
    try {
      const completed = await runTimelineSession(model, selectedLineIds, stopped);
      if (completed && !stopped()) model.setStatusNotice("連続再生が終わりました。");
    } catch (error) {
      if (!stopped()) model.setNotice(`連続再生を続けられません: ${(error as Error).message}`);
    } finally {
      if (model.playbackRun.current === run) {
        model.activeAudio.current = null;
        model.resolveActivePlayback.current = null;
        model.setPlayingLineId(null);
        model.setContinuousPlayback(false);
      }
    }
  };
}

export function createContinuousPlayback(model: PlaybackModel) {
  return createPlayback(model);
}
export function createSelectedPlayback(model: PlaybackModel, lineIds: string[]) {
  return createPlayback(model, lineIds);
}
