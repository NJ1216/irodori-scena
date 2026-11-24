import { useSyncExternalStore } from "react";

const pendingActions = new Map<string, number>();
const listeners = new Set<() => void>();
const confirmationWindowMs = 4_000;
type PendingNotice = { key: string; prompt: string; detail: string; actionLabel: string; expiresAt: number; clearMessage: () => void };
let activeNotice: PendingNotice | null = null;

function emitChange() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function isPending(key: string) {
  return (pendingActions.get(key) ?? 0) > Date.now();
}

export function useDestructiveConfirmation(key: string) {
  return useSyncExternalStore(
    subscribe,
    () => isPending(key),
    () => false,
  );
}

export function useDestructiveConfirmationNotice() {
  return useSyncExternalStore(
    subscribe,
    () => activeNotice,
    () => null,
  );
}

export function cancelDestructiveConfirmation() {
  if (!pendingActions.size && !activeNotice) return;
  activeNotice?.clearMessage();
  pendingActions.clear();
  activeNotice = null;
  emitChange();
}

export function pendingDestructiveConfirmationKey() {
  return activeNotice?.key ?? null;
}

/** Native WebView confirmation dialogs are inconsistent; use one shared
 * four-second, two-step rule for button and keyboard actions. */
export function confirmDestructiveAction(key: string, onPending: (message: string) => void, message: string, actionLabel = "削除", prompt = message, detail = message) {
  if (isPending(key)) {
    pendingActions.delete(key);
    if (activeNotice?.key === key) {
      activeNotice.clearMessage();
      activeNotice = null;
    }
    emitChange();
    return true;
  }
  if (activeNotice && activeNotice.key !== key) cancelDestructiveConfirmation();
  const expiresAt = Date.now() + confirmationWindowMs;
  pendingActions.set(key, expiresAt);
  activeNotice = { key, prompt, detail, actionLabel, expiresAt, clearMessage: () => onPending("") };
  emitChange();
  onPending(`${message} 4秒以内にもう一度実行すると${actionLabel}します。`);
  window.setTimeout(() => {
    if (pendingActions.get(key) === expiresAt && !isPending(key)) {
      pendingActions.delete(key);
      if (activeNotice?.key === key && activeNotice.expiresAt === expiresAt) {
        activeNotice.clearMessage();
        activeNotice = null;
      }
      emitChange();
    }
  }, confirmationWindowMs);
  return false;
}
