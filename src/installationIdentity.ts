let identity: string | null = "development";

export async function detectInstallationIdentity(): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    identity = await invoke<string | null>("installation_identity");
  } catch {
    // Browser-only development has no installer-owned identity file.
  }
}

export function installationIdentity(): string | null {
  return identity;
}
