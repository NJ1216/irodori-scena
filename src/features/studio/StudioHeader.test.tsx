import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { optimizationStatus } = vi.hoisted(() => ({ optimizationStatus: vi.fn() }));
vi.mock("../../api", () => ({ api: { optimizationStatus } }));

import { ProjectMenu } from "./StudioHeader";

describe("saved project menu", () => {
  beforeEach(() => vi.clearAllMocks());

  function model(isScratch: boolean) {
    return {
      busy: null,
      autoGenerateEnabled: false,
      workspace: { path: "/tmp/project.scena", name: "project.scena", isScratch },
      requestProjectMenuAction: vi.fn(),
      editSession: { runServer: (request: () => Promise<unknown>) => request() },
    };
  }

  it("enables optimization only when reclaimable data is found", async () => {
    const controller = model(false);
    optimizationStatus.mockResolvedValue({ available: true });
    render(<ProjectMenu model={controller as never} />);
    const action = screen.getByRole("button", { name: "最適化保存" });
    expect(action).toBeDisabled();
    fireEvent.pointerEnter(screen.getByRole("button", { name: "プロジェクト" }));
    await waitFor(() => expect(action).toBeEnabled());
    fireEvent.click(action);
    expect(controller.requestProjectMenuAction).toHaveBeenCalledWith("optimize");
  });

  it("keeps optimization disabled when there is nothing to reclaim", async () => {
    optimizationStatus.mockResolvedValue({ available: false });
    render(<ProjectMenu model={model(false) as never} />);
    const action = screen.getByRole("button", { name: "最適化保存" });
    fireEvent.pointerEnter(screen.getByRole("button", { name: "プロジェクト" }));
    await waitFor(() => expect(optimizationStatus).toHaveBeenCalledOnce());
    expect(action).toBeDisabled();
  });

  it("offers first save for an unsaved project", () => {
    render(<ProjectMenu model={model(true) as never} />);
    expect(screen.getByRole("button", { name: "保存" })).toBeEnabled();
  });
});
