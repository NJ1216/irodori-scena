import { createElement } from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { audioEngine } from "./audioEngine";
import { MasterAudioControls } from "./MasterAudioControls";
import { formatMasterVolume, masterVolumeAngle, stepMasterVolume } from "./masterVolumeScale";

describe("master volume control scale", () => {
  afterEach(() => vi.restoreAllMocks());

  it("places zero at twelve o'clock between the negative and positive sweeps", () => {
    expect(masterVolumeAngle(null)).toBe(-120);
    expect(masterVolumeAngle(-60)).toBeCloseTo(-115.2);
    expect(masterVolumeAngle(-10)).toBeLessThan(0);
    expect(masterVolumeAngle(0)).toBe(0);
    expect(masterVolumeAngle(3)).toBe(60);
    expect(masterVolumeAngle(6)).toBe(120);
  });

  it("uses finer steps toward zero decibels", () => {
    expect(stepMasterVolume(-40, 1)).toBe(-39);
    expect(stepMasterVolume(-20, 1)).toBe(-19.5);
    expect(stepMasterVolume(-1, 1)).toBe(-0.9);
    expect(stepMasterVolume(0, -1)).toBe(-0.1);
    expect(stepMasterVolume(0, 1)).toBe(0.1);
    expect(stepMasterVolume(6, 1)).toBe(6);
  });

  it("moves between minus sixty decibels and true silence at the left edge", () => {
    expect(stepMasterVolume(-60, -1)).toBeNull();
    expect(stepMasterVolume(null, 1)).toBe(-60);
    expect(formatMasterVolume(null)).toBe("−∞ dB");
    expect(formatMasterVolume(-0.1)).toBe("-0.1 dB");
    expect(formatMasterVolume(6)).toBe("+6 dB");
  });

  it("resets the knob to zero decibels with the context menu", () => {
    const setVolume = vi.spyOn(audioEngine, "setVolume").mockImplementation(() => undefined);
    render(createElement(MasterAudioControls));
    fireEvent.contextMenu(screen.getByRole("slider", { name: "マスターボリューム" }));
    expect(setVolume).toHaveBeenCalledWith(0);
  });

  it("steps the master volume with the vertical mouse wheel", () => {
    vi.spyOn(audioEngine, "getVolume").mockReturnValue(0);
    vi.spyOn(audioEngine, "subscribeVolume").mockImplementation((listener) => {
      listener(0);
      return () => undefined;
    });
    const setVolume = vi.spyOn(audioEngine, "setVolume").mockImplementation(() => undefined);
    render(createElement(MasterAudioControls));
    const knob = screen.getByRole("slider", { name: "マスターボリューム" });
    const upward = createEvent.wheel(knob, { deltaY: -100, cancelable: true });

    const dispatched = fireEvent(knob, upward);
    fireEvent.wheel(knob, { deltaY: 100 });
    fireEvent.wheel(knob, { deltaX: 100, deltaY: 0 });

    expect(dispatched).toBe(false);
    expect(setVolume.mock.calls).toEqual([[0.1], [0]]);
  });

  it("ends an outside release before later hover can change volume", () => {
    vi.spyOn(audioEngine, "getVolume").mockReturnValue(0);
    const setVolume = vi.spyOn(audioEngine, "setVolume").mockImplementation(() => undefined);
    render(createElement(MasterAudioControls));
    const knob = screen.getByRole("slider", { name: "マスターボリューム" });
    Object.assign(knob, { setPointerCapture: vi.fn() });

    fireEvent.pointerDown(knob, { pointerId: 1, button: 0, buttons: 1, clientY: 100 });
    fireEvent.pointerMove(knob, { pointerId: 1, buttons: 1, clientY: 98 });
    expect(setVolume).toHaveBeenCalledOnce();

    fireEvent.pointerUp(document.body, { pointerId: 1, button: 0, buttons: 0 });
    fireEvent.pointerMove(knob, { pointerId: 1, buttons: 0, clientY: 80 });
    fireEvent.pointerMove(knob, { pointerId: 1, buttons: 0, clientY: 70 });
    expect(setVolume).toHaveBeenCalledOnce();
  });

  it("clears dragging when pointer capture is lost", () => {
    const setVolume = vi.spyOn(audioEngine, "setVolume").mockImplementation(() => undefined);
    render(createElement(MasterAudioControls));
    const knob = screen.getByRole("slider", { name: "マスターボリューム" });
    Object.assign(knob, { setPointerCapture: vi.fn() });

    fireEvent.pointerDown(knob, { pointerId: 1, button: 0, buttons: 1, clientY: 100 });
    fireEvent.lostPointerCapture(knob, { pointerId: 1 });
    fireEvent.pointerMove(knob, { pointerId: 1, buttons: 1, clientY: 80 });
    expect(setVolume).not.toHaveBeenCalled();
  });

  it("lights the complete positive-decibel region while the held sample peak is clipped", () => {
    vi.spyOn(audioEngine, "subscribeLevels").mockImplementation((listener) => {
      listener({ left: -3, right: -3, leftSamplePeak: 3, rightSamplePeak: -1, leftPeak: 4, rightPeak: -1, active: true });
      return () => undefined;
    });
    render(createElement(MasterAudioControls));
    const [left, right] = screen.getAllByRole("meter");
    expect(left.querySelector("i")).toHaveStyle({ width: "86.36363636363636%" });
    expect(left.querySelector("em")).toHaveStyle({ left: "90.9090909090909%" });
    expect(left.querySelector("em")).toHaveClass("is-clipping");
    expect(left.querySelector("b")).toHaveClass("is-clipped");
    expect(right.querySelector("em")).not.toHaveClass("is-clipping");
    expect(right.querySelector("b")).not.toHaveClass("is-clipped");
  });
});
