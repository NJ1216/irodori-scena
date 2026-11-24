import type { LlmCard, OmlxRuntimeStatus } from "../../types";

export type RuntimeChoice = { value: string; label: string; version: string; installed: boolean; verified: boolean };

function installedChoices(card: LlmCard, status: OmlxRuntimeStatus | null) {
  const choices = new Map<string, RuntimeChoice>();
  for (const item of status?.catalog ?? []) {
    choices.set(item.id, { value: item.id, label: `oMLX ${item.omlxVersion} · SCENA検証済み`, version: item.omlxVersion, verified: true, installed: !!status?.installedRuntimes.some((runtime) => runtime.id === item.id && runtime.state === "ready") });
  }
  for (const item of status?.installedRuntimes ?? []) {
    if (choices.has(item.id)) continue;
    choices.set(item.id, { value: item.id, label: `oMLX ${item.omlxVersion} · ${item.state === "ready" ? "導入済み" : "未導入"}`, version: item.omlxVersion, installed: item.state === "ready", verified: false });
  }
  const current = currentRuntimeChoice(card);
  if (current && !choices.has(current.value)) choices.set(current.value, current);
  return choices;
}

export function runtimeChoices(card: LlmCard, status: OmlxRuntimeStatus | null, releases: Array<{ tag: string }>): RuntimeChoice[] {
  const choices = installedChoices(card, status);
  const knownVersions = new Set([...choices.values()].map((item) => item.version.replace(/^v/, "")));
  for (const release of releases) {
    if (knownVersions.has(release.tag.replace(/^v/, ""))) continue;
    const value = `release:${release.tag}`;
    choices.set(value, { value, label: `oMLX ${release.tag} · 公開版`, version: release.tag, installed: false, verified: false });
  }
  return [...choices.values()];
}

export function runtimeJobBusy(card: LlmCard) {
  const job = card.runtime?.job;
  return !!job && !["complete", "failed", "cancelled", "interrupted"].includes(job.state);
}

function currentRuntimeChoice(card: LlmCard): RuntimeChoice | null {
  if (!card.runtimeId) return null;
  return { value: card.runtimeId, label: `oMLX ${card.runtime?.version ?? "登録済みの版"} · 現在`, version: card.runtime?.version ?? "登録済みの版", installed: card.runtime?.state === "ready", verified: !!card.runtime?.recommended };
}

export function modelTestDisabled(card: LlmCard) {
  return card.source !== "remote" && card.runtime?.state !== "ready";
}

export function runtimeCurrentValue(card: LlmCard) {
  if (!card.runtimeId) return "";
  return card.runtime?.state === "ready" ? card.runtimeId : `bound:${card.runtimeId}`;
}
