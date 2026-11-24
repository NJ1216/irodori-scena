import type { PlaybackModel } from "./useStudioPlayback";
import { timelineApi, createTimelineLease, type TimelineLease, type TimelinePlan } from "./timelineApi";
import { TimelinePlaybackAudio } from "./timelinePlaybackAudio";
import { createRenderJob, enqueueRenderJobs, nextRenderSequence, type RenderJob } from "./renderJobQueue";

type QueueModel = PlaybackModel & {
  autoRenderQueue?: { current: RenderJob[] };
  processAutoRenderQueueRef?: { current: () => Promise<void> };
  editSession?: { capture: () => { generation: number } };
  playbackProtectedLineIds?: { current: Set<string> };
};

function promoteDependencies(model: QueueModel, ids: string[], plan: TimelinePlan) {
  const project = model.projectRef.current;
  if (!project || !model.autoGenerateEnabledRef.current || !model.autoRenderQueue) return;
  model.autoRenderQueue.current = model.autoRenderQueue.current.map((job) => (job.cause === "playback-required" && !ids.includes(job.lineId) ? { ...job, cause: "missing-take" } : job));
  const missingAudio = new Map(plan.units.flatMap((unit) => unit.members.filter((member) => member.duration === null && member.takeId).map((member) => [member.id, member.takeId])));
  const lines = project.scenes.flatMap((scene) => scene.lines).filter((line) => ids.includes(line.id));
  const jobs = lines.map((line) => createRenderJob(project, line, nextRenderSequence(), { mode: "append", cause: "playback-required", missingAudioTakeId: missingAudio.get(line.id) }, model.editSession?.capture().generation ?? 0));
  model.autoRenderQueue.current = enqueueRenderJobs(model.autoRenderQueue.current, jobs);
  void model.processAutoRenderQueueRef?.current();
}

function waitingLines(model: QueueModel, ids: string[]) {
  const lines = model.projectRef.current?.scenes.flatMap((scene) => scene.lines) ?? [];
  const labels = new Map(lines.map((line, index) => [line.id, `${index + 1}行「${line.text.slice(0, 20)}」`]));
  const visible = ids
    .slice(0, 3)
    .map((id) => labels.get(id) ?? "削除された行")
    .join(" / ");
  return ids.length > 3 ? `${visible} ほか${ids.length - 3}行` : visible;
}

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 100);
    signal.addEventListener("abort", finish, { once: true });
    if (signal.aborted) finish();
  });
}

function memberStarts(plan: TimelinePlan) {
  return new Map(plan.units.flatMap((unit) => unit.members.map((member) => [member.id, unit.start + member.offset] as const)));
}

class PlaybackSession {
  private cursor?: number;
  private targets: string[];
  private anchor: string;
  private previousStarts: Map<string, number>;
  private excluded: Set<string>;

  constructor(
    private model: QueueModel,
    private plan: TimelinePlan,
    private selectedIds: string[] | undefined,
    private audio: TimelinePlaybackAudio,
    private signal: AbortSignal,
    private stopped: () => boolean,
    private lease: TimelineLease,
  ) {
    const all = plan.units.flatMap((unit) => unit.members.map((member) => member.id));
    const index = selectedIds ? 0 : Math.max(0, all.indexOf(model.focusedLineId ?? ""));
    this.targets = selectedIds ? all.filter((id) => selectedIds.includes(id)) : all.slice(index);
    this.anchor = this.targets[0];
    this.previousStarts = memberStarts(plan);
    this.excluded = new Set(all.slice(0, index));
  }

  private async locate() {
    if (this.cursor !== undefined) return true;
    const unit = this.plan.units.find((unit) => unit.members.some((member) => member.id === this.anchor));
    if (!unit) {
      this.cursor = this.plan.endFrame;
      return true;
    }
    if (unit.startResolved) {
      this.cursor = unit.start + (unit.members.find((member) => member.id === this.anchor)?.offset ?? 0);
      return true;
    }
    promoteDependencies(this.model, unit.dependencies, this.plan);
    this.model.setStatusNotice(`再生開始位置の確定を待っています… ${waitingLines(this.model, unit.dependencies)}`);
    await pause(this.signal);
    this.plan = await timelineApi.plan(this.plan.projectId, this.signal, this.lease);
    return false;
  }

  private adopt(plan: TimelinePlan) {
    const nextStarts = memberStarts(plan);
    for (const [id, start] of nextStarts) {
      if (start < this.cursor! && this.previousStarts.get(id) !== start) this.excluded.add(id);
    }
    this.previousStarts = nextStarts;
    this.plan = plan;
    this.targets = (this.selectedIds ?? plan.units.flatMap((unit) => unit.members.map((member) => member.id))).filter((id) => !this.excluded.has(id));
  }

  private publishDependencies(intervals: import("./timelineApi").TimelineInterval[]) {
    const missing = [...new Set(intervals.flatMap((interval) => interval.dependencyLineIds))];
    promoteDependencies(this.model, missing, this.plan);
    if (this.model.playbackProtectedLineIds) this.model.playbackProtectedLineIds.current = new Set(intervals.flatMap((interval) => interval.events.map((event) => event.lineId)));
  }

  private async consume(current: import("./timelineApi").TimelineInterval) {
    if (current.status === "failed") throw new Error(current.error ?? "区間音声の準備に失敗しました。");
    if (current.status === "ready" || current.status === "silence") {
      await this.audio.prepare(current, this.signal);
      if (this.stopped() || this.signal.aborted) return;
      if (await this.audio.schedule(current)) {
        this.cursor = current.endFrame;
        this.model.setStatusNotice("共通タイムラインを再生しています。");
      }
      return;
    }
    const missing = current.dependencyLineIds;
    this.model.setStatusNotice(missing.length ? `音声を待っています… ${waitingLines(this.model, missing)}${this.model.autoGenerateEnabledRef.current ? "" : "（自動生成OFF）"}` : "次の区間の音声を準備しています…");
    if (current.status === "stale") this.plan = await timelineApi.plan(this.plan.projectId, this.signal, this.lease);
    await pause(this.signal);
  }

  private targetEnd() {
    let end = 0;
    for (const unit of this.plan.units) {
      for (const member of unit.members) {
        if (!this.targets.includes(member.id)) continue;
        if (!unit.startResolved || member.duration === null) return undefined;
        end = Math.max(end, unit.start + member.offset + member.duration);
      }
    }
    return end;
  }

  async step() {
    if (!(await this.locate())) return false;
    const end = this.targetEnd();
    if (end !== undefined && this.cursor! >= end) {
      if (!this.audio.aheadSeconds()) return true;
      await pause(this.signal);
      // Edits/appends during the last reserved interval still belong to this run.
      this.adopt(await timelineApi.plan(this.plan.projectId, this.signal, this.lease));
      return false;
    }
    if (this.audio.aheadSeconds() > 1.5) {
      await pause(this.signal);
      return false;
    }
    const response = await timelineApi.prepare(this.plan, this.cursor!, this.targets, this.signal, this.lease);
    if (this.stopped() || this.signal.aborted) return false;
    if (response.status === "stale") {
      this.adopt(response.plan);
      return false;
    }
    this.publishDependencies(response.intervals);
    const current = response.intervals[0];
    if (current) await this.consume(current);
    else await pause(this.signal);
    return false;
  }
}

export async function runTimelineSession(model: QueueModel, selectedIds: string[] | undefined, stopped: () => boolean) {
  const project = model.projectRef.current;
  if (!project) return false;
  const run = model.playbackRun.current;
  const lease = createTimelineLease();
  const controller = new AbortController();
  const audio = new TimelinePlaybackAudio();
  model.resolveActivePlayback.current = () => {
    controller.abort();
    audio.close();
  };
  const display = window.setInterval(() => {
    if (!stopped()) model.setPlayingLineId(audio.activeIds().join("|") || null);
  }, 20);
  try {
    const plan = await timelineApi.plan(project.id, controller.signal, lease);
    const session = new PlaybackSession(model, plan, selectedIds, audio, controller.signal, stopped, lease);
    while (!stopped() && !controller.signal.aborted && model.projectRef.current?.id === project.id) {
      if (await session.step()) return true;
    }
    return false;
  } finally {
    controller.abort();
    void timelineApi.stop(lease).catch(() => undefined);
    window.clearInterval(display);
    audio.close();
    if (model.playbackRun.current === run) model.playbackProtectedLineIds?.current.clear();
    void model.processAutoRenderQueueRef?.current();
  }
}
