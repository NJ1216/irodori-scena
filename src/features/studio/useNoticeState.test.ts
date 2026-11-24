// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useNoticeState } from "./useNoticeState";

it("counts every notice call, including a repeated text and an updater", () => {
  const { result } = renderHook(() => useNoticeState("読み込み中…"));
  const setNotice = result.current.setNotice;
  expect(result.current).toMatchObject({ notice: "読み込み中…", noticeSerial: 0 });
  act(() => result.current.setNotice("失敗しました。"));
  act(() => result.current.setNotice("失敗しました。"));
  expect(result.current).toMatchObject({ notice: "失敗しました。", noticeSerial: 2 });
  act(() => result.current.setNotice((current) => `${current} 再試行してください。`));
  expect(result.current).toMatchObject({ notice: "失敗しました。 再試行してください。", noticeSerial: 3 });
  expect(result.current.setNotice).toBe(setNotice);
});

it("updates a status notice without counting it as a new notice", () => {
  const { result } = renderHook(() => useNoticeState("読み込み中…"));
  act(() => result.current.setNotice("保存しました。"));
  const before = result.current;
  act(() => result.current.setStatusNotice("共通タイムラインを再生しています。"));
  expect(result.current).toMatchObject({ notice: "共通タイムラインを再生しています。", noticeSerial: 1 });
  const afterStatus = result.current;
  act(() => result.current.setStatusNotice("共通タイムラインを再生しています。"));
  expect(result.current.notice).toBe(afterStatus.notice);
  expect(result.current.setStatusNotice).toBe(before.setStatusNotice);
});
