export function notebookActionSpacerHeight({ contentEnd, lastLineTop, ruleHeight }: { contentEnd: number; lastLineTop: number; ruleHeight: number }) {
  if (!Number.isFinite(ruleHeight) || ruleHeight <= 0) return 0;
  const availableHeight = Math.max(0, lastLineTop - contentEnd);
  return Math.floor(availableHeight / ruleHeight) * ruleHeight;
}
