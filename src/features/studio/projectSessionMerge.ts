// Three-way reconciliation keeps edits made since a request began. ID-bearing
// collections preserve local additions/deletions and the order changed locally.
function same(left: unknown, right: unknown) {
  return left === right || JSON.stringify(left) === JSON.stringify(right);
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function identified(values: unknown[]): values is Array<Record<string, unknown> & { id: string }> {
  return values.every((value) => record(value) && typeof value.id === "string");
}
function mergeArray(base: unknown[], local: unknown[], remote: unknown[]): unknown[] {
  if (!identified(base) || !identified(local) || !identified(remote)) return local;
  const byId = (values: typeof base) => new Map(values.map((value) => [value.id, value]));
  const before = byId(base),
    current = byId(local),
    incoming = byId(remote);
  const localOrder = local.map((value) => value.id);
  const order = same(
    localOrder,
    base.map((value) => value.id),
  )
    ? remote.map((value) => value.id)
    : localOrder;
  const ids = [...new Set([...order, ...incoming.keys(), ...current.keys()])];
  return ids.flatMap((id) => {
    const old = before.get(id),
      latest = current.get(id),
      next = incoming.get(id);
    if (!latest && old) return [];
    if (!next && same(latest, old)) return [];
    return [mergeProjectValue(old, latest, next)];
  });
}
export function mergeProjectValue(base: unknown, local: unknown, remote: unknown): unknown {
  if (same(local, base)) return remote;
  if (same(remote, base)) return local;
  if (Array.isArray(base) && Array.isArray(local) && Array.isArray(remote)) return mergeArray(base, local, remote);
  if (record(base) && record(local) && record(remote)) {
    const merged: Record<string, unknown> = {};
    for (const key of new Set([...Object.keys(base), ...Object.keys(local), ...Object.keys(remote)])) {
      const value = mergeProjectValue(base[key], local[key], remote[key]);
      if (value !== undefined) merged[key] = value;
    }
    return merged;
  }
  return local;
}

export function projectMergeConflicts(base: unknown, local: unknown, remote: unknown, path = "project"): string[] {
  if (same(local, base) || same(remote, base) || same(local, remote)) return [];
  if (record(base) && record(local) && record(remote)) {
    return [...new Set([...Object.keys(base), ...Object.keys(local), ...Object.keys(remote)])].flatMap((key) => projectMergeConflicts(base[key], local[key], remote[key], `${path}.${key}`));
  }
  if (Array.isArray(base) && Array.isArray(local) && Array.isArray(remote) && identified(base) && identified(local) && identified(remote)) {
    const byId = (values: typeof base) => new Map(values.map((value) => [value.id, value]));
    const before = byId(base),
      current = byId(local),
      incoming = byId(remote);
    return [...new Set([...before.keys(), ...current.keys(), ...incoming.keys()])].flatMap((id) => projectMergeConflicts(before.get(id), current.get(id), incoming.get(id), `${path}[${id}]`));
  }
  return [path];
}
