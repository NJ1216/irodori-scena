import type { Page, Route } from "@playwright/test";
import type { StudioProject } from "../../src/types";
import { placeTimelineUnits, type TimelinePlan } from "../../src/features/studio/timelineApi";
import { testToneWav } from "./audio-fixtures";
import { json } from "./mock-api-response";

const sampleRate = 8_000;

function timelinePlan(project: StudioProject): TimelinePlan {
  const groups: Array<{ id: string; gap: number; members: Array<{ id: string; offset: number; duration: number | null; takeId: string; signature: string | null }> }> = [];
  for (const line of project.scenes.flatMap((scene) => scene.lines).filter((line) => line.enabled !== false)) {
    const take = line.takes.find((take) => take.id === line.selectedTakeId);
    const member = { id: line.id, offset: Math.round((line.startOffsetSeconds ?? 0) * sampleRate), duration: take?.durationSeconds !== undefined ? Math.round(take.durationSeconds * sampleRate) : null, takeId: take?.id ?? "", signature: take?.id ?? null };
    const previous = groups.at(-1);
    if (line.cueId && previous?.id === line.cueId) previous.members.push(member);
    else groups.push({ id: line.cueId ?? line.id, gap: Math.round((line.gapSeconds ?? project.settings.lineGap ?? 0.7) * sampleRate), members: [member] });
  }
  const units = placeTimelineUnits(groups);
  return { planId: `e2e-${project.revision}`, generation: project.revision, projectId: project.id, sampleRate, resolved: units.every((unit) => unit.resolved), endFrame: Math.max(0, ...units.map((unit) => unit.start + unit.duration)), units };
}

export async function installTimelineMedia(page: Page) {
  await page.route("**/api/media/timeline-e2e-*.wav", (route) => {
    const duration = Number(new URL(route.request().url()).pathname.match(/timeline-e2e-(\d+)\.wav$/)?.[1]) / sampleRate;
    return route.fulfill({ body: testToneWav(duration), contentType: "audio/wav" });
  });
}

export async function fulfillTimeline(route: Route, project: StudioProject, audioUrl?: string) {
  const path = new URL(route.request().url()).pathname;
  if (!path.startsWith("/api/project/timeline/")) return false;
  if (path.endsWith("/stop")) return json(route, { stopped: true }).then(() => true);
  if (path.endsWith("/background")) return json(route, { queued: true }).then(() => true);
  const plan = timelinePlan(project);
  if (path.endsWith("/plan")) return json(route, plan).then(() => true);
  if (!path.endsWith("/prepare")) return false;
  const body = route.request().postDataJSON();
  const targets = new Set<string>(body.target_line_ids);
  const events = plan.units.flatMap((unit) => unit.members.filter((member) => targets.has(member.id)).map((member) => ({ lineId: member.id, startFrame: unit.start + member.offset, endFrame: unit.start + member.offset + (member.duration ?? 0) })));
  const missing = plan.units.flatMap((unit) => unit.members.filter((member) => targets.has(member.id) && member.duration === null).map((member) => member.id));
  const start = body.start_frame as number;
  const end = Math.min((Math.floor(start / sampleRate) + 1) * sampleRate, Math.max(start + (missing.length ? sampleRate : 0), ...events.map((event) => event.endFrame)));
  const dependencies = plan.units.filter((unit) => unit.start < end && unit.start + Math.max(unit.duration, sampleRate) > start).flatMap((unit) => unit.members.filter((member) => targets.has(member.id) && member.duration === null).map((member) => member.id));
  const interval = {
    intervalId: `${plan.planId}-${start}`,
    planId: plan.planId,
    generation: plan.generation,
    startFrame: start,
    endFrame: end,
    sampleRate,
    status: dependencies.length ? "waiting-input" : "ready",
    audioUrl: audioUrl ?? `/api/media/timeline-e2e-${end - start}.wav`,
    dependencyLineIds: dependencies,
    events,
  };
  return json(route, { status: "ready", plan, intervals: start < end || dependencies.length ? [interval] : [] }).then(() => true);
}
