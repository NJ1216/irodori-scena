export function autoGenerationDisabled(busy: string | null, cancelRequested: boolean) {
  return busy === "export" && cancelRequested;
}
