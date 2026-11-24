const STYLE_GUIDE_ROUTE_EVENT = "scena-style-guide-route";

export function isStyleGuideLocation(location: Pick<Location, "pathname" | "search"> = window.location) {
  return location.pathname === "/style-guide" || new URLSearchParams(location.search).has("style-guide");
}

function announceRouteChange() {
  window.dispatchEvent(new Event(STYLE_GUIDE_ROUTE_EVENT));
}

export function openStyleGuide() {
  if (isStyleGuideLocation()) return;
  const url = new URL(window.location.href);
  url.searchParams.set("style-guide", "");
  url.hash = "";
  window.history.pushState(null, "", url);
  announceRouteChange();
}

export function closeStyleGuide() {
  const url = new URL(window.location.href);
  url.pathname = url.pathname === "/style-guide" ? "/" : url.pathname;
  url.searchParams.delete("style-guide");
  url.hash = "";
  window.history.replaceState(null, "", url);
  announceRouteChange();
}

export function subscribeToStyleGuideRoute(callback: () => void) {
  window.addEventListener("popstate", callback);
  window.addEventListener(STYLE_GUIDE_ROUTE_EVENT, callback);
  return () => {
    window.removeEventListener("popstate", callback);
    window.removeEventListener(STYLE_GUIDE_ROUTE_EVENT, callback);
  };
}
