import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DialogFooter, DialogHeader, ModalBackdrop } from "./overlays";
import { prepareModalFileDrop } from "./modalFileDrop";

describe("dialog layout", () => {
  it("provides a shared title header and action footer", () => {
    const { container } = render(
      <section className="modal" role="dialog" aria-labelledby="dialog-title">
        <DialogHeader eyebrow="DIALOG" title="共通ダイアログ" titleId="dialog-title" description="説明" />
        <p>本文</p>
        <DialogFooter>
          <button type="button">キャンセル</button>
          <button type="button" className="primary">
            確認
          </button>
        </DialogFooter>
      </section>,
    );

    expect(screen.getByRole("dialog", { name: "共通ダイアログ" })).toBeVisible();
    expect(container.querySelector(".dialog-header")).toContainElement(screen.getByRole("heading", { name: "共通ダイアログ" }));
    expect(container.querySelector(".dialog-header")).not.toContainElement(screen.getByText("説明"));
    expect(container.querySelector(".dialog-intro")).toContainElement(screen.getByText("説明"));
    expect(container.querySelector(".dialog-footer")).toContainElement(screen.getByRole("button", { name: "確認" }));
  });
});

describe("modal dismissal", () => {
  it("blocks file drops by default and dismisses only opted-in dialogs", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <ModalBackdrop onClose={onClose}>
        <div />
      </ModalBackdrop>,
    );
    expect(prepareModalFileDrop()).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
    rerender(
      <ModalBackdrop onClose={onClose} fileDropPolicy="dismiss">
        <div />
      </ModalBackdrop>,
    );
    expect(prepareModalFileDrop()).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes the top modal with Escape", async () => {
    const onClose = vi.fn();
    render(
      <ModalBackdrop onClose={onClose}>
        <section role="dialog" aria-label="確認">
          内容
        </section>
      </ModalBackdrop>,
    );

    expect(screen.getByRole("dialog", { name: "確認" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("ignores backdrop clicks while disabled", async () => {
    const onClose = vi.fn();
    const { container } = render(
      <ModalBackdrop onClose={onClose} disabled>
        <section>内容</section>
      </ModalBackdrop>,
    );
    await userEvent.click(container.querySelector(".modal-backdrop")!);
    expect(onClose).not.toHaveBeenCalled();
  });
});
