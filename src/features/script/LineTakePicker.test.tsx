// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LineTakePicker } from "./LineTakePicker";

describe("LineTakePicker", () => {
  it("uses the shared rate for legacy blank line overrides", () => {
    render(
      <LineTakePicker
        line={{
          id: "line-1",
          characterId: "cast-1",
          text: "テストです。",
          stageDirection: "",
          speechRate: "" as unknown as number,
          selectedTakeId: "take-1",
          takes: [
            {
              id: "take-1",
              audioUrl: "/media/take.wav",
              seed: 1,
              quality: "fast",
              stageDirection: "",
              createdAt: 1,
            },
          ],
        }}
        downloadFileName="take.wav"
        busy={false}
        defaultSpeechRate={1.2}
        onNotice={vi.fn()}
        onDeleteTake={vi.fn().mockResolvedValue(undefined)}
        onSelectTake={vi.fn()}
      />,
    );

    expect(screen.getByRole("tooltip")).toHaveTextContent("1.20");
  });

  it("shows the generating TTS model immediately before the WAV save button", () => {
    render(
      <LineTakePicker
        line={{
          id: "line-1",
          characterId: "cast-1",
          text: "テストです。",
          stageDirection: "",
          selectedTakeId: "take-1",
          takes: [
            {
              id: "take-1",
              audioUrl: "/media/take.wav",
              seed: 1,
              quality: "fast",
              stageDirection: "",
              createdAt: 1,
              ttsConfiguration: {
                engineCommit: null,
                modelRevision: "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
                codecRevision: null,
                optimizationProfile: null,
              },
            },
          ],
        }}
        downloadFileName="take.wav"
        busy={false}
        defaultSpeechRate={1.2}
        onNotice={vi.fn()}
        onDeleteTake={vi.fn().mockResolvedValue(undefined)}
        onSelectTake={vi.fn()}
      />,
    );

    const tag = screen.getByTitle("音声モデル: Irodori-TTS v4.1 Small");
    const save = screen.getByRole("button", { name: "このテイクのWAVを保存" });
    expect(tag).toHaveTextContent("v4.1 Small");
    expect(tag.nextElementSibling).toBe(save);
  });
});
