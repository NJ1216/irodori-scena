import { describe, expect, it } from "vitest";
import { LineTextLocalHistory } from "./lineTextLocalHistory";

const snapshot = (text: string) => ({ text, pronunciations: [] });

describe("LineTextLocalHistory", () => {
  it("clears redo after a new edit", () => {
    const history = new LineTextLocalHistory(snapshot("a"));
    history.record(snapshot("ab"), 1, 2);
    expect(history.undo()?.text).toBe("a");
    history.record(snapshot("ac"), 1, 2);
    expect(history.redo()).toBeNull();
  });

  it("discards stale history after an external replacement", () => {
    const history = new LineTextLocalHistory(snapshot("a"));
    history.record(snapshot("ab"), 1, 2);
    history.sync(snapshot("server"));
    expect(history.undo()).toBeNull();
  });
});
