// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import type { ScriptAssistantGroup } from "./scriptAssistantTypes";
import { ScriptAssistantPreview } from "./ScriptAssistantPreview";

const group = (atomic: boolean): ScriptAssistantGroup => ({
  id: "group-1",
  sceneId: "scene-1",
  sceneTitle: "駅前",
  atomic,
  contiguous: true,
  originalRows: [
    {
      id: "line-1",
      characterId: "cast-a",
      characterName: "彩",
      text: "元の台詞",
      stageDirection: "小声で",
      enabled: true,
      hasTakes: true,
    },
  ],
  rows: [
    {
      id: "row-1",
      originalLineId: "line-1",
      characterId: "cast-a",
      characterName: "彩",
      text: "別の表現",
      stageDirection: "穏やかに",
      speechRate: 1,
      gapSeconds: 0.7,
    },
  ],
  warnings: ["部分提案です。"],
});

const characters = [
  {
    id: "cast-a",
    name: "彩",
    profile: "",
    voiceKeywords: "",
    referenceAudioUrl: "",
    referenceFile: "",
    createdAt: 1,
    avatarThumbnailUrl: "/media/aya.png",
    avatarVersion: 2,
  },
] as Character[];

describe("ScriptAssistantPreview", () => {
  it("accepts independently usable rows without discarding partial output", async () => {
    const onRowsChange = vi.fn();
    const { container } = render(<ScriptAssistantPreview groups={[group(false)]} characters={characters} acceptedRows={new Set()} acceptedGroups={new Set()} onRowsChange={onRowsChange} onGroupsChange={vi.fn()} />);

    expect(screen.getByText("元の台詞")).toBeVisible();
    expect(screen.getByText("別の表現")).toBeVisible();
    expect(screen.getByText("小声で")).toBeVisible();
    expect(screen.getByText("穏やかに")).toBeVisible();
    expect(screen.getByText("書き直し前")).toBeVisible();
    expect(screen.getByText("提案")).toBeVisible();
    expect(container.querySelectorAll(".script-assistant-speaker-avatar img")).toHaveLength(2);
    expect(screen.getByText("部分提案です。")).toBeVisible();
    await userEvent.click(screen.getByRole("checkbox", { name: "彩の提案を採用" }));
    expect([...onRowsChange.mock.calls[0][0]]).toEqual(["row-1"]);
  });

  it("accepts a line-count-changing rewrite only as one atomic group", async () => {
    const onGroupsChange = vi.fn();
    render(<ScriptAssistantPreview groups={[group(true)]} characters={characters} acceptedRows={new Set()} acceptedGroups={new Set()} onRowsChange={vi.fn()} onGroupsChange={onGroupsChange} />);

    expect(screen.getByRole("checkbox", { name: "この提案全体を採用" })).toBeVisible();
    expect(screen.getByRole("region", { name: "書き直し前" })).toHaveTextContent("小声で");
    expect(screen.getByRole("region", { name: "提案" })).toHaveTextContent("穏やかに");
    await userEvent.click(screen.getByRole("checkbox", { name: "この提案全体を採用" }));
    expect([...onGroupsChange.mock.calls[0][0]]).toEqual(["group-1"]);
  });
});
