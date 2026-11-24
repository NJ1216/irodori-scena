export type ParticleDeletionDiagnostic = {
  at: string;
  target: "cast" | "line" | "scene";
  itemId?: string;
  phase: string;
  durationMs: number;
  count: number;
  outcome: "ready" | "failed" | "cancelled";
  error?: string;
  imageWidth?: number;
  imageHeight?: number;
  particleCount?: number;
  initialParticleCount?: number;
  renderer?: "webgl2" | "canvas2d" | "dom";
  fallbackReason?: string;
  drawMedianMs?: number;
  drawP95Ms?: number;
  frameMedianMs?: number;
  frameP95Ms?: number;
};

const key = "scena-particle-deletion-diagnostics";
const limit = 40;
const events: ParticleDeletionDiagnostic[] = [];

const DELIBERATE_CANCEL_REASONS = new Set(["superseded", "cleared", "confirmation-expired", "unmounted"]);

export class ParticlePreparationFailure extends Error {
  constructor(
    readonly phase: string,
    cause: unknown,
  ) {
    super(cause instanceof Error ? cause.message : String(cause), { cause });
    this.name = "ParticlePreparationFailure";
  }
}

/** True only for deliberate cancellations (the user moved on); timeouts and capture failures stay failures. */
export function particleCancelled(signal: AbortSignal) {
  return signal.aborted && typeof signal.reason === "string" && DELIBERATE_CANCEL_REASONS.has(signal.reason);
}

type ParticleRenderFields = Pick<ParticleDeletionDiagnostic, "particleCount" | "initialParticleCount" | "renderer" | "fallbackReason" | "drawMedianMs" | "drawP95Ms" | "frameMedianMs" | "frameP95Ms">;

/** The renderer metrics every particle-deletion diagnostic reports, copied from the dissolve renderer's result. */
export function particleRenderFields(metrics: ParticleRenderFields): ParticleRenderFields {
  return {
    particleCount: metrics.particleCount,
    initialParticleCount: metrics.initialParticleCount,
    renderer: metrics.renderer,
    fallbackReason: metrics.fallbackReason,
    drawMedianMs: metrics.drawMedianMs,
    drawP95Ms: metrics.drawP95Ms,
    frameMedianMs: metrics.frameMedianMs,
    frameP95Ms: metrics.frameP95Ms,
  };
}

export function particleFailurePhase(error: unknown) {
  return error instanceof ParticlePreparationFailure ? error.phase : "unknown";
}

export function particleFailureMessage(error: unknown) {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

export function recordParticleDeletionDiagnostic(event: Omit<ParticleDeletionDiagnostic, "at">, cause?: unknown) {
  if (!import.meta.env.DEV) return;
  const entry = { at: new Date().toISOString(), ...event, durationMs: Math.round(event.durationMs) };
  events.push(entry);
  if (events.length > limit) events.shift();
  try {
    sessionStorage.setItem(key, JSON.stringify(events));
  } catch {
    /* Diagnostics must not affect deletion. */
  }
  if (event.outcome === "failed") console.error("[SCENA particle deletion]", entry, cause);
}

export function particleDeletionDiagnostics() {
  return events.map((event) => ({ ...event }));
}

declare global {
  interface Window {
    __SCENA_PARTICLE_DELETION_DIAGNOSTICS__?: { read: typeof particleDeletionDiagnostics };
  }
}

if (import.meta.env.DEV && typeof window !== "undefined") {
  try {
    events.push(...(JSON.parse(sessionStorage.getItem(key) ?? "[]") as ParticleDeletionDiagnostic[]).slice(-limit));
  } catch {
    /* Ignore damaged diagnostics. */
  }
  window.__SCENA_PARTICLE_DELETION_DIAGNOSTICS__ = { read: particleDeletionDiagnostics };
}
