import { expect, test } from "@playwright/test";
import { testToneWav } from "./audio-fixtures";
import { installMockApi } from "./mock-api";

const pixelPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

test("does not reopen the dialog notice for playback status while a cast avatar is open", async ({ page }) => {
  const project = await installMockApi(page, { generatedTake: true, completeTakes: true, lineCount: 4, takeDurationSeconds: 2 });
  const cast = project.characters[0];
  Object.assign(cast, { avatarUrl: "/media/avatar-e2e.png", avatarThumbnailUrl: "/media/avatar-e2e.png", avatarOriginalUrl: "/media/avatar-e2e.png" });
  await page.route("**/media/avatar-e2e.png*", (route) => route.fulfill({ body: pixelPng, contentType: "image/png" }));
  await page.route("**/api/media/**/*.wav", (route) => route.fulfill({ body: testToneWav(2), contentType: "audio/wav" }));
  await page.goto("/");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  await expect(page.locator(".notice-screen-reader-text")).toHaveText("共通タイムラインを再生しています。");

  await page
    .getByRole("button", { name: `${cast.name}の原画像を表示` })
    .first()
    .click();
  await expect(page.getByRole("dialog", { name: `${cast.name}の原画像` })).toBeVisible();

  // Playback keeps scheduling intervals (each at most one second) while the avatar stays open.
  for (let elapsed = 0; elapsed < 3_000; elapsed += 250) {
    await expect(page.getByRole("button", { name: "通知を閉じる" })).toHaveCount(0);
    await page.waitForTimeout(250);
  }
  await expect(page.getByRole("button", { name: "■ 停止" })).toBeVisible();
});
