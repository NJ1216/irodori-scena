import { describe, expect, it } from "vitest";
import type { DialogueLine, StudioProject } from "../../types";
import { createRenderJob, dequeueRenderJob, enqueueRenderJobs, isCurrentRenderJob, requeueInterruptedJob } from "./renderJobQueue";

function fixture() {
  const line = { id: "line", characterId: "cast", text: "本文", stageDirection: "静かに", takes: [], selectedTakeId: null } as DialogueLine;
  const project = {
    id: "project",
    revision: 1,
    characters: [{ id: "cast", referenceVersion: 2 }],
    scenes: [{ id: "scene", title: "scene", lines: [line] }],
    settings: { quality: "fast", speechRate: 1, textCfg: 1, voiceCfg: 1, captionCfg: 1, steps: 16 },
  } as StudioProject;
  return { project, line };
}

describe("render job queue", () => {
  it("keeps repeated manual clicks FIFO while coalescing automatic intent", () => {
    const { project, line } = fixture();
    const missing = createRenderJob(project, line, 1, { mode: "append", cause: "missing-take" });
    const manualOne = createRenderJob(project, line, 2, { mode: "append", cause: "manual-new-take" });
    const manualTwo = createRenderJob(project, line, 3, { mode: "append", cause: "manual-new-take" });
    const editedOld = createRenderJob(project, line, 4, { mode: "append", cause: "line-edited" });
    line.text = "更新";
    const editedNew = createRenderJob(project, line, 5, { mode: "append", cause: "line-edited" });
    const queue = enqueueRenderJobs([missing, editedOld], [manualOne, manualTwo, editedNew]);
    expect(queue.map((job) => job.jobId)).toEqual([manualOne.jobId, manualTwo.jobId, editedNew.jobId]);
  });

  it("keeps one latest edited job per line without changing manual priority", () => {
    const { project, line } = fixture();
    const manual = createRenderJob(project, line, 1, { mode: "append", cause: "manual-new-take" });
    const rate = createRenderJob(project, line, 2, { mode: "append", cause: "line-edited" });
    line.speechRate = 1.2;
    const cfg = createRenderJob(project, line, 3, { mode: "append", cause: "line-edited" });
    expect(enqueueRenderJobs([manual, rate], [cfg]).map((job) => job.jobId)).toEqual([manual.jobId, cfg.jobId]);
  });

  it("replaces 200 pending line edits with their latest settings", () => {
    const { project, line } = fixture();
    project.scenes[0].lines = Array.from({ length: 200 }, (_, index) => ({ ...line, id: `line-${index}` }));
    const first = project.scenes[0].lines.map((item) => createRenderJob(project, item, 1, { mode: "append", cause: "line-edited" }));
    project.scenes[0].lines.forEach((item) => {
      item.speechRate = 1.2;
    });
    const latest = project.scenes[0].lines.map((item) => createRenderJob(project, item, 2, { mode: "append", cause: "line-edited" }));
    const queue = enqueueRenderJobs(first, latest);
    expect(queue).toHaveLength(200);
    expect(queue.map((job) => job.jobId)).toEqual(latest.map((job) => job.jobId));
  });

  it("rejects stale replacement targets and changed render inputs", () => {
    const { project, line } = fixture();
    line.takes = [{ id: "take-1", audioUrl: "/one.wav", seed: 1, quality: "fast", stageDirection: "", createdAt: 1 }];
    line.selectedTakeId = "take-1";
    const job = createRenderJob(project, line, 1, { mode: "replace", cause: "manual-replace", targetTakeId: "take-1" });
    line.selectedTakeId = null;
    expect(isCurrentRenderJob(project, line, job)).toBe(false);
    line.selectedTakeId = "take-1";
    line.text = "別本文";
    expect(isCurrentRenderJob(project, line, job)).toBe(false);
  });

  it("rejects completion from an older project generation even when IDs and text match", () => {
    const { project, line } = fixture();
    const job = createRenderJob(project, line, 1, { mode: "append", cause: "missing-take" }, 4);
    expect(isCurrentRenderJob(project, line, job, 4)).toBe(true);
    expect(isCurrentRenderJob(project, line, job, 5)).toBe(false);
  });

  it.each(["playback-required", "last-take-deleted", "missing-take"] as const)("drops an obsolete %s intent after another operation has supplied its selected take", (cause) => {
    const { project, line } = fixture();
    const job = createRenderJob(project, line, 1, { mode: "append", cause });
    line.takes = [{ id: "take-1", audioUrl: "/one.wav", seed: 1, quality: "fast", stageDirection: "", createdAt: 1 }];
    line.selectedTakeId = "take-1";

    expect(isCurrentRenderJob(project, line, job)).toBe(false);
  });

  it("requeues an interrupted job only once without changing its intent", () => {
    const { project, line } = fixture();
    const job = createRenderJob(project, line, 1, { mode: "append", cause: "manual-seed", seed: 42 });
    const once = requeueInterruptedJob([], job);
    expect(once[0]).toMatchObject({ jobId: job.jobId, mode: "append", seed: 42, interruptionCount: 1 });
    expect(requeueInterruptedJob([], once[0])).toEqual([]);
  });

  it("does not restore an interrupted edit over a newer edit with the same signature", () => {
    const { project, line } = fixture();
    const old = createRenderJob(project, line, 1, { mode: "append", cause: "line-edited" });
    const latest = createRenderJob(project, line, 2, { mode: "append", cause: "line-edited" });
    expect(requeueInterruptedJob([latest], old)).toEqual([latest]);
  });

  it("runs manual, then committed edits, then playback lookahead, then the youngest current script line", () => {
    const { project, line } = fixture();
    const younger = { ...structuredClone(line), id: "younger" };
    const older = { ...structuredClone(line), id: "older" };
    project.scenes[0].lines = [younger, line, older];
    const queue = enqueueRenderJobs(
      [],
      [
        createRenderJob(project, older, 1, { mode: "append", cause: "missing-take" }),
        createRenderJob(project, line, 2, { mode: "append", cause: "line-edited" }),
        createRenderJob(project, younger, 3, { mode: "append", cause: "dictionary" }),
        createRenderJob(project, older, 4, { mode: "append", cause: "manual-new-take" }),
        createRenderJob(project, line, 5, { mode: "append", cause: "playback-required" }),
      ],
    );

    expect(dequeueRenderJob(queue, project, new Set())?.cause).toBe("manual-new-take");
    expect(dequeueRenderJob(queue, project, new Set())?.cause).toBe("line-edited");
    expect(dequeueRenderJob(queue, project, new Set())?.cause).toBe("playback-required");
    expect(dequeueRenderJob(queue, project, new Set())?.lineId).toBe(younger.id);
    expect(dequeueRenderJob(queue, project, new Set())?.lineId).toBe(older.id);
  });

  it("uses the latest script order after queued lines are moved", () => {
    const { project, line } = fixture();
    const moved = { ...structuredClone(line), id: "moved" };
    project.scenes[0].lines = [line, moved];
    const queue = enqueueRenderJobs([], [createRenderJob(project, line, 1, { mode: "append", cause: "missing-take" }), createRenderJob(project, moved, 2, { mode: "append", cause: "missing-take" })]);
    project.scenes[0].lines = [moved, line];

    expect(dequeueRenderJob(queue, project, new Set())?.lineId).toBe(moved.id);
  });

  it("upgrades a normal missing job to one playback obligation without duplicating it", () => {
    const { project, line } = fixture();
    const missing = createRenderJob(project, line, 1, { mode: "append", cause: "missing-take" });
    const required = createRenderJob(project, line, 2, { mode: "append", cause: "playback-required" });
    const upgraded = enqueueRenderJobs([missing], [required]);
    expect(upgraded).toHaveLength(1);
    expect(upgraded[0].cause).toBe("playback-required");
    expect(enqueueRenderJobs(upgraded, [missing])).toEqual(upgraded);
  });

  it("coalesces final-take deletion with missing generation without downgrading playback urgency", () => {
    const { project, line } = fixture();
    const deleted = createRenderJob(project, line, 1, { mode: "append", cause: "last-take-deleted" });
    const required = createRenderJob(project, line, 2, { mode: "append", cause: "playback-required" });
    const missing = createRenderJob(project, line, 3, { mode: "append", cause: "missing-take" });

    const queue = enqueueRenderJobs([], [deleted, required, missing]);

    expect(queue).toHaveLength(1);
    expect(queue[0].cause).toBe("playback-required");
  });
});

it("regenerates only the exact take whose WAV was confirmed missing", () => {
  const { project, line } = fixture();
  line.takes = [{ id: "missing", audioUrl: "/missing.wav", seed: 1, quality: "fast", stageDirection: "", createdAt: 1 }];
  line.selectedTakeId = "missing";
  const job = createRenderJob(project, line, 1, { mode: "append", cause: "playback-required", missingAudioTakeId: "missing" });
  expect(isCurrentRenderJob(project, line, job)).toBe(true);
  line.takes.push({ ...line.takes[0], id: "new" });
  line.selectedTakeId = "new";
  expect(isCurrentRenderJob(project, line, job)).toBe(false);
});
