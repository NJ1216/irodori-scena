import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { VoiceDesignForm, type VoiceDesignSuggestedField } from "./VoiceDesignForm";
import { emptyVoiceDesign, type VoiceDesign } from "./voiceDesign";

function Harness() {
  const [value, setValue] = useState<VoiceDesign>(emptyVoiceDesign);
  const [suggested, setSuggested] = useState<Set<VoiceDesignSuggestedField>>(new Set(["age", "qualities"]));
  return (
    <VoiceDesignForm
      value={value}
      suggested={suggested}
      onChange={(next, field) => {
        setValue(next);
        setSuggested((current) => {
          const copy = new Set(current);
          copy.delete(field);
          return copy;
        });
      }}
    />
  );
}

describe("VoiceDesignForm", () => {
  it("supports clearing single selection and unrestricted multi-selection without closing", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const age = screen.getByRole("button", { name: "年齢" });
    await user.click(age);
    await user.click(screen.getByRole("option", { name: "小学校低学年" }));
    expect(age).toHaveTextContent("小学校低学年");
    expect(age.closest("label")).not.toHaveClass("is-ai-suggested");
    await user.click(screen.getByRole("button", { name: "声質" }));
    await user.click(screen.getByRole("checkbox", { name: "太い" }));
    await user.click(screen.getByRole("checkbox", { name: "細い" }));
    expect(screen.getByRole("checkbox", { name: "太い" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "細い" })).toBeChecked();
  });

  it("opens from the keyboard and closes with Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const gender = screen.getByRole("button", { name: "性別" });
    gender.focus();
    await user.keyboard("{ArrowDown}");
    expect(gender).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(gender).toHaveAttribute("aria-expanded", "false");
  });
});
