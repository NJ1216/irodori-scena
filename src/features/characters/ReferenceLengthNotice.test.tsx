// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ReferenceLengthNotice } from "./ReferenceLengthNotice";

const emotionIds = { normal: "n", joy: "j", anger: "a", sorrow: "s", delight: "d" };

it("warns before saving how many seconds the 120-second reference will drop", () => {
  const candidates = ["b", "n", "j", "a", "s", "d"].map((id) => ({ id, durationSeconds: 30 }));
  render(<ReferenceLengthNotice candidates={candidates} baselineCandidateId="b" emotionCandidateIds={emotionIds} />);
  expect(screen.getByRole("status")).toHaveTextContent("120秒");
  expect(screen.getByRole("status")).toHaveTextContent("63.5秒");
});

it("stays hidden while the selected clips fit", () => {
  const candidates = ["b", "n", "j", "a", "s", "d"].map((id) => ({ id, durationSeconds: 15 }));
  render(<ReferenceLengthNotice candidates={candidates} baselineCandidateId="b" emotionCandidateIds={emotionIds} />);
  expect(screen.queryByRole("status")).toBeNull();
});
