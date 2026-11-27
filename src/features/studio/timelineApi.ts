import { request } from "../../api-core";

export type TimelineMember = { id: string; offset: number; duration: number | null; takeId: string; signature: string | null };
export type TimelineUnit = { id: string; start: number; duration: number; resolved: boolean; startResolved: boolean; dependencies: string[]; members: TimelineMember[] };
export type TimelinePlan = { planId: string; generation: number; projectId: string; sampleRate: number; endFrame: number; resolved: boolean; units: TimelineUnit[] };
export type TimelineEvent = { lineId: string; startFrame: number; endFrame: number };
export type TimelineInterval = {
  intervalId: string;
  planId: string;
  generation: number;
  startFrame: number;
  endFrame: number;
  sampleRate: number;
  status: "waiting-input" | "queued" | "rendering" | "ready" | "silence" | "stale" | "failed";
  audioUrl: string | null;
  dependencyLineIds: string[];
  events: TimelineEvent[];
  error?: string;
};
const clientId = crypto.randomUUID();
let sequence = 0;
export type TimelineLease = { client_id: string; playback_id: string; sequence: number };
export function createTimelineLease(): TimelineLease {
  return { client_id: clientId, playback_id: crypto.randomUUID(), sequence: ++sequence };
}
export const timelineApi = {
  stop: (lease: TimelineLease) => request("/api/project/timeline/stop", { method: "POST", body: JSON.stringify(lease) }),
  plan: (projectId: string, signal: AbortSignal, lease: TimelineLease) => request<TimelinePlan>("/api/project/timeline/plan", { method: "POST", signal, body: JSON.stringify({ project_id: projectId, ...lease }) }),
  prepare: (plan: TimelinePlan, start: number, targets: string[], signal: AbortSignal, lease: TimelineLease) =>
    request<{ status: string; plan: TimelinePlan; intervals: TimelineInterval[] }>("/api/project/timeline/prepare", {
      method: "POST",
      signal,
      body: JSON.stringify({ project_id: plan.projectId, plan_id: plan.planId, start_frame: start, target_line_ids: targets, ...lease }),
    }),
};

export function placeTimelineUnits<Unit extends { gap: number; members: Array<{ id: string; offset?: number; duration: number | null }> }>(units: Unit[]) {
  let start = 0;
  let dependencies: string[] = [];
  return units.map((unit) => {
    const duration = Math.max(0, ...unit.members.map((member) => (member.offset ?? 0) + (member.duration ?? 0)));
    const result = { ...unit, start, duration, startResolved: !dependencies.length, resolved: !dependencies.length && unit.members.every((member) => member.duration !== null), dependencies: [...dependencies] };
    dependencies = [...dependencies, ...unit.members.filter((member) => member.duration === null).map((member) => member.id)];
    start = Math.max(0, start + duration + unit.gap);
    return result;
  });
}
