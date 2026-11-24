const LINE_JUMP_EVENT = "scena-line-jump-input";

export function showLineJumpInput(value: string | null) {
  window.dispatchEvent(new CustomEvent<string | null>(LINE_JUMP_EVENT, { detail: value }));
}

export function listenForLineJumpInput(listener: (value: string | null) => void) {
  const handle = (event: Event) => listener((event as CustomEvent<string | null>).detail);
  window.addEventListener(LINE_JUMP_EVENT, handle);
  return () => window.removeEventListener(LINE_JUMP_EVENT, handle);
}
