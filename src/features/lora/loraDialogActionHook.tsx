// Keep TSX so the DEV transform records custom-hook signatures for Fast Refresh.
import { useRef, useState } from "react";

export type LoraDialogAction = (action: () => Promise<void>) => Promise<void>;
export function useLoraDialogAction() {
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const perform: LoraDialogAction = async (action) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return { busy, error, perform };
}
