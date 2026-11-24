/** The trained combined-reference limit of Irodori-TTS v4.1; the server joins clips up to it. */
export const MAX_REFERENCE_SECONDS = 120;
const CLIP_GAP_SECONDS = 0.7;

type TimedCandidate = { id: string; durationSeconds?: number };

/** Seconds of the selected baseline and emotion clips that the joined reference would drop from its end. */
export function referenceOverflowSeconds(candidates: TimedCandidate[], baselineCandidateId: string | null, emotionCandidateIds: Partial<Record<string, string>>): number {
  if (!baselineCandidateId) return 0;
  const byId = new Map(candidates.map((candidate) => [candidate.id, candidate]));
  const durations = [baselineCandidateId, ...Object.values(emotionCandidateIds)].map((id) => (id ? byId.get(id)?.durationSeconds : undefined)).filter((seconds): seconds is number => typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0);
  const total = durations.reduce((sum, seconds) => sum + seconds, 0) + Math.max(0, durations.length - 1) * CLIP_GAP_SECONDS;
  return Math.max(0, total - MAX_REFERENCE_SECONDS);
}
