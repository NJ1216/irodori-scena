import { useEffect, useRef, useState } from "react";
import type { Character } from "../../types";
import { captureCastSnapshot, castSnapshotTimeoutMs, disposeCastSnapshot, type CastSnapshot } from "./castSnapshot";
import { castDeletionDurationMs } from "./castParticles";
import { particleFailureMessage, particleFailurePhase, recordParticleDeletionDiagnostic, particleCancelled } from "../shared/particleDeletionDiagnostics";

type Deletion = { characters: Character[]; name: string; phase: "pending" | "dissolving"; image: CastSnapshot | null };
type Preparation = { id: string; region: HTMLElement; controller: AbortController; result: Promise<CastSnapshot | null>; expiry: number };

/** Capture particles when available; confirmed deletion retains a visible DOM fallback. */
export function useCastDeletion(characters: Character[], onDelete: (character: Character, beforeDelete?: () => Promise<void>) => Promise<boolean>) {
  const [deletion, setDeletion] = useState<Deletion | null>(null);
  const locked = useRef(false);
  const mounted = useRef(false);
  const preparation = useRef<Preparation | null>(null);

  function clearPreparation(abort: boolean, reason = "superseded") {
    const current = preparation.current;
    if (!current) return;
    window.clearTimeout(current.expiry);
    if (abort) current.controller.abort(reason);
    preparation.current = null;
  }

  function prepare(character: Character, region: HTMLElement) {
    const current = preparation.current;
    if (current?.id === character.id && current.region === region && !current.controller.signal.aborted) return current.result;
    clearPreparation(true);
    const controller = new AbortController();
    const started = performance.now();
    const timeout = window.setTimeout(() => controller.abort("capture-timeout"), castSnapshotTimeoutMs);
    const result = Promise.race([captureCastSnapshot(region, controller.signal), new Promise<never>((_, reject) => controller.signal.addEventListener("abort", () => reject(new Error(String(controller.signal.reason))), { once: true }))])
      .then(
        (image) => {
          if (controller.signal.aborted) {
            disposeCastSnapshot(image);
            recordParticleDeletionDiagnostic({ target: "cast", itemId: character.id, phase: "aborted", durationMs: performance.now() - started, count: 1, outcome: particleCancelled(controller.signal) ? "cancelled" : "failed", error: String(controller.signal.reason) });
            return null;
          }
          recordParticleDeletionDiagnostic({ target: "cast", itemId: character.id, phase: "prepared", durationMs: performance.now() - started, count: 1, outcome: "ready", imageWidth: image.canvas.width, imageHeight: image.canvas.height });
          return image;
        },
        (error: unknown) => {
          recordParticleDeletionDiagnostic(
            {
              target: "cast",
              itemId: character.id,
              phase: controller.signal.aborted ? "aborted" : particleFailurePhase(error),
              durationMs: performance.now() - started,
              count: 1,
              outcome: particleCancelled(controller.signal) ? "cancelled" : "failed",
              error: controller.signal.aborted ? String(controller.signal.reason) : particleFailureMessage(error),
            },
            error,
          );
          return null;
        },
      )
      .finally(() => window.clearTimeout(timeout));
    const expiry = window.setTimeout(() => {
      if (preparation.current?.controller === controller) clearPreparation(true, "confirmation-expired");
    }, 4_000);
    preparation.current = { id: character.id, region, controller, result, expiry };
    return result;
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearPreparation(true, "unmounted");
    };
  }, []);
  useEffect(() => {
    if (deletion?.phase !== "dissolving") return;
    const image = deletion.image;
    const timer = window.setTimeout(() => {
      setDeletion(null);
      locked.current = false;
    }, castDeletionDurationMs);
    return () => {
      window.clearTimeout(timer);
      disposeCastSnapshot(image);
    };
  }, [deletion]);

  async function remove(character: Character, region?: HTMLElement | null) {
    if (locked.current) return;
    locked.current = true;
    const snapshot: Deletion = { characters, name: character.name, phase: "pending", image: null };
    const ready = region ? prepare(character, region) : Promise.resolve(null);
    if (!region) recordParticleDeletionDiagnostic({ target: "cast", itemId: character.id, phase: "region", durationMs: 0, count: 1, outcome: "failed", error: "No deletion region" });
    let deleted = false;
    try {
      deleted = await onDelete(character, async () => {
        setDeletion(snapshot);
        if (preparation.current?.id === character.id) window.clearTimeout(preparation.current.expiry);
        const image = await ready;
        if (!mounted.current) {
          clearPreparation(true, "capture-failed");
          throw new Error("キャスト画面が閉じられたため削除を中断しました。");
        }
        clearPreparation(!image, image ? "capture-complete" : "capture-failed");
        snapshot.image = image;
      });
    } finally {
      if (mounted.current) {
        setDeletion(deleted ? { ...snapshot, phase: "dissolving" } : null);
        if (!deleted) {
          disposeCastSnapshot(snapshot.image);
          locked.current = false;
        }
      }
    }
  }

  return { deletion, remove, characters: deletion?.characters ?? characters };
}
