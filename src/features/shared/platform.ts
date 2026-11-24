/** The webview host controls desktop shortcuts; browser development follows its host. */
export function isWindows() {
  return typeof navigator !== "undefined" && /Win/i.test(navigator.platform);
}

export function primaryModifier(event: Pick<KeyboardEvent, "ctrlKey" | "metaKey">) {
  return isWindows() ? event.ctrlKey && !event.metaKey : event.metaKey && !event.ctrlKey;
}

export function shortcutLabel(value: string) {
  return isWindows() ? value.replaceAll("⌘", "Ctrl+").replaceAll("⌥", "Alt+").replaceAll("⇧", "Shift+") : value;
}

export function preventWindowsWebViewShortcutDefault(event: KeyboardEvent) {
  if (isWindows() && primaryModifier(event) && !event.altKey && ["KeyR", "KeyP"].includes(event.code)) event.preventDefault();
}
