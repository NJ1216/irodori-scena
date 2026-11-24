import { describe, expect, it } from "vitest";
import fixtures from "../../../tests/fixtures/timeline/placement.json";
import { placeTimelineUnits } from "./timelineApi";

describe("shared project placement", () => {
  it.each(fixtures)("$name", (fixture) => {
    const units = placeTimelineUnits(fixture.units);
    expect(units.map((unit) => unit.start)).toEqual(fixture.starts);
    expect(units.map((unit) => unit.resolved)).toEqual(fixture.resolved);
    expect(Math.max(...units.map((unit) => unit.start + unit.duration))).toBe(fixture.end);
    expect(units.map((unit) => unit.gap)).toEqual(fixture.units.map((unit) => unit.gap));
  });
});
