import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api-runtime";
import type { CastImportPreparation } from "../../types";
import { CastImportDialog } from "./CastImportDialog";

vi.mock("../../api-runtime", () => ({ apiFetch: vi.fn() }));
vi.mock("../../api", () => ({ api: { cancelCastImport: vi.fn(), commitCastImport: vi.fn() } }));

const cast = { id: "cast", name: "彩", profile: "", voiceKeywords: "", referenceAudioUrl: "/voice.wav", referenceFile: "/voice.wav", createdAt: 1 };
const preparation = {
  sessionId: "session",
  expiresInSeconds: 60,
  errors: [],
  items: [{ key: "conflict", path: "duplicate.scenacast", status: "conflict", incoming: cast, existing: cast }],
} satisfies CastImportPreparation;

describe("CastImportDialog incoming media", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("does not create an object URL when the dialog unmounts before the fetch resolves", async () => {
    let resolveFetch!: (value: unknown) => void;
    vi.mocked(apiFetch).mockReturnValue(new Promise((resolve) => (resolveFetch = resolve)) as never);
    const createObjectURL = vi.fn(() => "blob:late");
    const original = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL };
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    try {
      const view = render(<CastImportDialog preparation={preparation} onClose={vi.fn()} onApplied={vi.fn()} />);
      view.unmount();
      resolveFetch({ ok: true, blob: async () => new Blob(["x"]) });
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      Object.assign(URL, original);
    }
  });
});
