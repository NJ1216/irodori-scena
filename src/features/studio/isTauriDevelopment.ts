export function isTauriDevelopment() {
  return import.meta.env.DEV && (globalThis as { isTauri?: boolean }).isTauri === true;
}
