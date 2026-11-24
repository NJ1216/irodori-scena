import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AboutDialog } from "./AboutDialog";
import { loadLicenseNotices, type Notices } from "./licenseNotices";

vi.mock("../../api", () => ({ openExternal: vi.fn() }));
vi.mock("./licenseNotices", async (original) => ({ ...(await original<typeof import("./licenseNotices")>()), loadLicenseNotices: vi.fn() }));
const notices: Notices = {
  applicationLicense: "Application MIT permission.",
  entries: Array.from({ length: 100 }, (_, index) => ({ id: `${index}`, name: index === 0 ? "React" : `Library ${index}`, version: "19", license: "MIT", source: "https://react.dev", scope: "build-and-application", status: "collected", texts: [{ name: "LICENSE", sha256: "text" }] })),
  texts: { text: "Copyright Example\nPermission is granted." },
};
beforeEach(() => vi.mocked(loadLicenseNotices).mockReset());
describe("AboutDialog", () => {
  it("renders a bounded list and only the selected license body", async () => {
    vi.mocked(loadLicenseNotices).mockResolvedValue(notices);
    render(<AboutDialog onClose={vi.fn()} />);
    const list = await screen.findByRole("navigation", { name: "使用ライブラリ" });
    expect(within(list).getAllByRole("button")).toHaveLength(30);
    expect(screen.queryByText(/Permission is granted/)).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "React 19" }));
    expect(screen.getAllByText(/Permission is granted/)).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "次のページ" }));
    expect(within(screen.getByRole("navigation", { name: "使用ライブラリ" })).queryByText("React")).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "unmatched");
    expect(screen.getByText("使用ライブラリ · 0 件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "次のページ" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "前のページ" })).toBeDisabled();
  });
  it("can retry a failed load and ignores results after closing", async () => {
    vi.mocked(loadLicenseNotices).mockRejectedValueOnce(new Error("corrupt"));
    const { unmount } = render(<AboutDialog onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("読み込めません"));
    let resolve!: (value: Notices) => void;
    vi.mocked(loadLicenseNotices).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    await userEvent.click(screen.getByRole("button", { name: "再読み込み" }));
    expect(screen.getByRole("status")).toHaveTextContent("読み込み中");
    unmount();
    expect(vi.mocked(loadLicenseNotices).mock.calls[1][0].aborted).toBe(true);
    resolve(notices);
  });
});
