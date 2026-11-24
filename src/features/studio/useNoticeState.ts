import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

/**
 * The studio notice text plus a serial that changes on every result notice, so a repeated result still counts as new.
 * Status notices (ongoing state such as playback or progress) only update the text: they keep the serial, so the dialog
 * overlay never shows them, and a repeated status text changes nothing.
 */
export function useNoticeState(initial: string) {
  const [state, setState] = useState({ notice: initial, noticeSerial: 0 });
  const setNotice: Dispatch<SetStateAction<string>> = useCallback((value) => setState((current) => ({ notice: typeof value === "function" ? value(current.notice) : value, noticeSerial: current.noticeSerial + 1 })), []);
  const setStatusNotice = useCallback((value: string) => setState((current) => (current.notice === value ? current : { ...current, notice: value })), []);
  return { notice: state.notice, noticeSerial: state.noticeSerial, setNotice, setStatusNotice };
}
