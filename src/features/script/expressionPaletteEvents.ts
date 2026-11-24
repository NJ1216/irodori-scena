const TOGGLE_EXPRESSION_PALETTE_EVENT = "scena-toggle-expression-palette";

export function requestExpressionPaletteToggle() {
  window.dispatchEvent(new Event(TOGGLE_EXPRESSION_PALETTE_EVENT));
}

export function listenForExpressionPaletteToggle(listener: () => void) {
  window.addEventListener(TOGGLE_EXPRESSION_PALETTE_EVENT, listener);
  return () => window.removeEventListener(TOGGLE_EXPRESSION_PALETTE_EVENT, listener);
}
