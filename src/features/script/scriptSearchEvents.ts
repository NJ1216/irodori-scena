const SEARCH_EVENT = "scena-open-script-search";
export function requestScriptSearch() {
  window.dispatchEvent(new Event(SEARCH_EVENT));
}
export function listenForScriptSearch(listener: () => void) {
  window.addEventListener(SEARCH_EVENT, listener);
  return () => window.removeEventListener(SEARCH_EVENT, listener);
}
