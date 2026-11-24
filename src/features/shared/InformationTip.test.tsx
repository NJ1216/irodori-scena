import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InformationTip } from "./InformationTip";

describe("InformationTip", () => {
  it("shares its description with hover and keyboard focus and keeps the portal on screen", () => {
    vi.stubGlobal("innerWidth", 360);
    render(<InformationTip ariaLabel="保存先の説明" paragraphs={["SCENAの説明", "PROJECTの説明"]} />);
    const button = screen.getByLabelText("保存先の説明");
    vi.spyOn(button, "getBoundingClientRect").mockReturnValue({ left: 350, right: 368, top: 20, bottom: 38, width: 18, height: 18, x: 350, y: 20, toJSON: () => ({}) });
    expect(button).toHaveAttribute("aria-describedby");
    fireEvent.mouseEnter(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("SCENAの説明PROJECTの説明");
    expect(screen.getByRole("tooltip")).toHaveClass("is-below");
    expect(screen.getByRole("tooltip")).toHaveStyle({ left: "188px" });
    fireEvent.mouseLeave(button);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.blur(button);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
