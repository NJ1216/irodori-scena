type Props = Record<string, unknown>;

function sameValue(left: unknown, right: unknown) {
  if (Object.is(left, right)) return true;
  // Arrays such as the rewrite targets and the free cue casts are rebuilt on every scene render.
  return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((item, index) => Object.is(item, right[index]));
}

export function sameLineEditorProps(previous: Readonly<Props>, next: Readonly<Props>) {
  const keys = new Set([...Object.keys(previous), ...Object.keys(next)]);
  for (const key of keys) if (!sameValue(previous[key], next[key])) return false;
  return true;
}
