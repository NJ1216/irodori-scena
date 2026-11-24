type Addition = { state: string; error?: string; preparation?: { state: string; stage?: string | null; errorCategory?: string | null; message: string } };
const terminal = new Set(["complete", "failed", "cancelled", "interrupted"]);

export function additionState(status: Addition): string {
  return status.preparation?.state ?? status.state;
}

export function additionFinished(status: Addition): boolean {
  return terminal.has(additionState(status));
}

export function additionError(status: Addition): string {
  return status.preparation?.message || status.error || "モデル追加を完了できませんでした。";
}
