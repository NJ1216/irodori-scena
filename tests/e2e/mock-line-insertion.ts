import type { Route } from "@playwright/test";
import type { projectFixture } from "./mock-api-fixtures";

export async function fulfillLineInsertion(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const match = new URL(request.url()).pathname.match(/^\/api\/scenes\/([^/]+)\/lines$/);
  if (!match || request.method() !== "POST") return false;
  const scene = project.scenes.find((item) => item.id === match[1]);
  if (!scene) {
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    return true;
  }
  const body = request.postDataJSON();
  const sourceIndex = scene.lines.findIndex((item) => item.id === body.split_line_id);
  if (sourceIndex >= 0 && typeof body.split_offset === "number") {
    const source = scene.lines[sourceIndex];
    const points = Array.from(source.text);
    const inherited = Object.fromEntries(["speechRate", "gapSeconds", "textCfg", "voiceCfg", "captionCfg"].filter((key) => Object.hasOwn(source, key)).map((key) => [key, source[key as keyof typeof source]]));
    const created = {
      id: `line-split-${scene.lines.length + 1}`,
      characterId: source.characterId,
      text: points.slice(body.split_offset).join(""),
      stageDirection: "",
      takes: [],
      selectedTakeId: null,
      ...(body.split_offset < points.length ? inherited : {}),
    };
    source.text = points.slice(0, body.split_offset).join("");
    source.selectedTakeId = null;
    scene.lines.splice(sourceIndex + 1, 0, created);
  } else {
    const beforeIndex = body.before_line_id ? scene.lines.findIndex((item) => item.id === body.before_line_id) : scene.lines.length;
    const insertIndex = beforeIndex >= 0 ? beforeIndex : scene.lines.length;
    const nearby = scene.lines[insertIndex] ?? scene.lines.at(-1);
    scene.lines.splice(insertIndex, 0, {
      id: `line-insert-${scene.lines.length + 1}`,
      characterId: nearby?.characterId ?? project.characters[0]?.id ?? "",
      text: "",
      stageDirection: "",
      takes: [],
      selectedTakeId: null,
    });
  }
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  return true;
}
