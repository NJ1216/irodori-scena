type Entry = { policy: "dismiss" | "block"; dismiss: () => void };
const policies = new Map<number, Entry>();

export function registerModalFileDrop(layer: number, entry: Entry) {
  policies.set(layer, entry);
  return () => policies.delete(layer);
}

export function prepareModalFileDrop() {
  const mountedBackdropCount = typeof document === "undefined" ? 0 : document.querySelectorAll(".modal-backdrop").length;
  if (mountedBackdropCount > policies.size) return false;
  if (!policies.size) return true;
  const entry = policies.get(Math.max(...policies.keys()));
  if (!entry || entry.policy === "block") return false;
  entry.dismiss();
  return true;
}
