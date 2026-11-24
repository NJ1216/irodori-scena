export function includePinnedCueIndexes(visible: number[], ...indexes: Array<number | undefined>) {
  const pinned = indexes.filter((index): index is number => index !== undefined && !visible.includes(index));
  return pinned.length ? [...new Set([...visible, ...pinned])].sort((a, b) => a - b) : visible;
}
