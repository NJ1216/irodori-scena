// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ScriptAssistantTargetLines } from "./ScriptAssistantTargetLines";
import { formatTargetLineNumbers } from "./scriptAssistantTargetLineNumbers";

it("shows only the selected line numbers", () => {
  render(
    <ScriptAssistantTargetLines
      project={
        {
          scenes: [
            {
              id: "scene",
              title: "場面",
              lines: [
                { id: "one", characterId: "a", text: "一行目", stageDirection: "", takes: [], selectedTakeId: null },
                { id: "three", characterId: "b", text: "三行目", stageDirection: "", takes: [], selectedTakeId: null },
              ],
            },
          ],
        } as unknown as import("../../types").StudioProject
      }
      originalIds={["one", "three"]}
      onChange={() => {}}
      lines={[
        {
          line: { id: "one", characterId: "a", text: "一行目", stageDirection: "", takes: [], selectedTakeId: null },
          lineNumber: 1,
        },
        {
          line: {
            id: "three",
            characterId: "b",
            text: "三行目",
            stageDirection: "小声で",
            takes: [],
            selectedTakeId: null,
          },
          lineNumber: 3,
        },
      ]}
    />,
  );

  const summary = screen.getByLabelText("書き直し対象 2行: 1、3");
  expect(within(summary).queryByText("一行目")).not.toBeInTheDocument();
  expect(summary).toHaveTextContent("1、3");
  expect(within(summary).getAllByText(/^[13]$/)).toHaveLength(2);
});

it("compresses long and sparse selections into readable ranges", () => {
  const lines = [1, 2, 3, 7, 10, 11, 12].map((lineNumber) => ({
    line: { id: String(lineNumber), characterId: "a", text: "", stageDirection: "", takes: [], selectedTakeId: null },
    lineNumber,
  }));
  expect(formatTargetLineNumbers(lines)).toBe("1〜3、7、10〜12");
  expect(
    formatTargetLineNumbers(
      Array.from({ length: 100 }, (_, index) => ({
        line: { id: String(index), characterId: "a", text: "", stageDirection: "", takes: [], selectedTakeId: null },
        lineNumber: index + 1,
      })),
    ),
  ).toBe("1〜100");
});

it("includes the whole simultaneous cue when a range endpoint is one cue member", async () => {
  const row = (id: string, cueId?: string) => ({ id, characterId: "a", text: id, stageDirection: "", takes: [], selectedTakeId: null, cueId });
  const lines = [row("one", "cue"), row("two", "cue"), row("three")];
  const onChange = vi.fn();
  render(<ScriptAssistantTargetLines project={{ scenes: [{ id: "scene", title: "場面", lines }] } as unknown as import("../../types").StudioProject} lines={[{ line: lines[2], lineNumber: 2 }]} originalIds={["three"]} onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "編集" }));
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "開始行" }), "two");
  await userEvent.click(screen.getByRole("button", { name: "適用" }));
  expect(onChange).toHaveBeenCalledWith(["one", "two", "three"]);
});
