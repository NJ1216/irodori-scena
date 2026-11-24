import { describe, expect, it } from "vitest";
import { isMeanFlowSelection, MEANFLOW_MODEL_REPO, MEANFLOW_MODEL_REVISION, takeSamplingPresentation } from "./ttsSampling";

describe("isMeanFlowSelection", () => {
  it("requires the pinned MF repository and revision", () => {
    const selection = { engine: { repo: null, commit: null, externalId: null }, model: { repo: MEANFLOW_MODEL_REPO, revision: MEANFLOW_MODEL_REVISION }, codecRevision: null, optimizationProfile: "upstream-meanflow" };
    expect(isMeanFlowSelection(selection)).toBe(true);
    expect(isMeanFlowSelection({ ...selection, model: { ...selection.model, revision: "other" } })).toBe(false);
  });

  it("labels MF takes independently from the legacy quality field", () => {
    expect(takeSamplingPresentation({ quality: "quality", ttsConfiguration: { modelRevision: MEANFLOW_MODEL_REVISION } } as never)).toEqual({ className: "quality-meanflow", label: "MF 4" });
  });
});
