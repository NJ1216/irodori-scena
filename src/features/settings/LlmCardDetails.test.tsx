// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { LlmCard, LlmEndpoint } from "../../types";
import { LlmCardDetails } from "./LlmCardDetails";

vi.mock("./LlmCardTestControls", () => ({ LlmCardTestControls: () => null }));

const card = { id: "c", endpointId: "e", modelId: "claude-sonnet-5-5", displayName: "Claude", source: "remote", testStatus: { state: "untested", checkedAt: null, errorCategory: null }, settings: { ttlSeconds: 300, memoryGuard: "safe", thinking: false } } as unknown as LlmCard;
const endpoint = (baseUrl: string) => ({ id: "e", provider: "openai", displayName: "e", baseUrl, hasCredential: true }) as LlmEndpoint;
const renderDetails = (baseUrl: string) => render(<LlmCardDetails card={card} endpoint={endpoint(baseUrl)} displayName="Claude" setDisplayName={() => undefined} settings={card.settings} setSettings={() => undefined} onTestComplete={() => undefined} />);

it("hides sampling controls that are never sent to Anthropic", () => {
  renderDetails("https://api.anthropic.com/v1");
  expect(screen.getByText(/claude-sonnet-5-5 \(Anthropic\)/)).toBeInTheDocument();
  expect(screen.queryByText("生成のばらつき")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Temperature/)).not.toBeInTheDocument();
  expect(screen.getByLabelText(/Thinkingを有効にする/)).toBeInTheDocument();
});

it("keeps sampling controls for other OpenAI-compatible endpoints", () => {
  renderDetails("https://api.openai.com/v1");
  expect(screen.getByText("生成のばらつき")).toBeInTheDocument();
  expect(screen.getByLabelText(/Temperature/)).toBeInTheDocument();
  expect(screen.getByLabelText(/Top-p/)).toBeInTheDocument();
});
