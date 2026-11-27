import { expect, type Page } from "@playwright/test";
import { installMockApi } from "./mock-api";
import { projectFixture } from "./mock-api-fixtures";

export async function openCasts(page: Page, failure = false, onlyOne = false, avatar = false, personality?: string, delayNextAvatar = false) {
  await installMockApi(page);
  const project = structuredClone(projectFixture);
  const details = project.characters[0].profileDetails;
  if (personality && details) details.personality = personality;
  if (onlyOne) project.characters = project.characters.slice(0, 1);
  if (avatar) {
    // Distinct saturated regions and pure white detect accidental background removal.
    for (const character of project.characters) Object.assign(character, { avatarThumbnailUrl: `/api/media/test-avatar-${character.id}.png` });
    await page.route("**/api/media/test-avatar-*.png*", async (route) => {
      const id = route.request().url().includes("cast-sara") ? "cast-sara" : "cast-ren";
      if (!project.characters.some((item) => item.id === id)) return route.fulfill({ status: 404 });
      if (delayNextAvatar && id === "cast-ren" && route.request().resourceType() === "image") await new Promise((resolve) => setTimeout(resolve, 500));
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192"><path fill="white" d="M0 0h192v192H0z"/><circle cx="75" cy="80" r="60" fill="#ee4477"/><path fill="#00aabb" d="M96 96h96v96H96z"/></svg>',
      });
    });
  }
  await page.route(/\/api\/project(?:\?|$)/, (route) => route.fulfill({ json: project }));
  let calls = 0;
  await page.route(/\/api\/characters\/cast-(?:sara|ren)$/, async (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1);
    calls += 1;
    if (failure) return route.fulfill({ status: 500, json: { detail: "test failure" } });
    project.characters = project.characters.filter((item) => item.id !== id);
    project.scenes.forEach((scene) =>
      scene.lines.forEach((line) => {
        if (line.characterId === id) line.characterId = "";
      }),
    );
    await route.fulfill({ json: project });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await expect(page.locator(".cast-notebook-spread h2")).toHaveText("佐倉 紗良");
  return () => calls;
}
