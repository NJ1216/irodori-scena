import { describe, expect, it } from "vitest";
import type { Character, Scene } from "../../types";
import { projectCharacterOrder, reorderProjectCharacters } from "./projectCharacterOrder";

describe("project character order", () => {
  it("prioritizes script speakers while preserving saved order within both groups", () => {
    const characters = ["unused-a", "used-a", "unused-b", "used-b"].map((id) => ({ id, name: id }) as Character);
    const scenes = [
      {
        id: "scene",
        title: "",
        lines: [
          { id: "line", characterId: "used-b" },
          { id: "line-2", characterId: "used-a" },
        ],
      },
    ] as Scene[];
    expect(projectCharacterOrder({ characters, scenes }).map((character) => character.id)).toEqual(["used-a", "used-b", "unused-a", "unused-b"]);
  });

  it.each([
    ["used-c", "used-a", ["used-c", "used-a", "used-b", "unused-a", "unused-b"]],
    ["used-a", null, ["used-b", "used-c", "used-a", "unused-a", "unused-b"]],
    ["unused-b", "unused-a", ["used-a", "used-b", "used-c", "unused-b", "unused-a"]],
  ] as const)("moves %s within its group", (dragged, before, expected) => {
    const characters = ["unused-a", "used-a", "unused-b", "used-b", "used-c"].map((id) => ({ id, name: id }) as Character);
    const scenes = [{ id: "scene", title: "", lines: ["used-a", "used-b", "used-c"].map((characterId, index) => ({ id: `line-${index}`, characterId })) }] as Scene[];
    const ordered = projectCharacterOrder({ characters: reorderProjectCharacters({ characters, scenes }, dragged, before), scenes });
    expect(ordered.map((character) => character.id)).toEqual(expected);
  });

  it("rejects a destination in the other group and keeps a single cast stable", () => {
    const characters = ["used", "unused"].map((id) => ({ id, name: id }) as Character);
    const scenes = [{ id: "scene", title: "", lines: [{ id: "line", characterId: "used" }] }] as Scene[];
    expect(reorderProjectCharacters({ characters, scenes }, "used", "unused").map((item) => item.id)).toEqual(["used", "unused"]);
    expect(reorderProjectCharacters({ characters: characters.slice(0, 1), scenes }, "used", null).map((item) => item.id)).toEqual(["used"]);
  });
});
