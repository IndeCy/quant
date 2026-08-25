import { getJson, postJson } from "../../shared/api/client";
import type { StrategyDraft, StrategyDraftPayload } from "./model";

export function listStrategyDrafts(): Promise<StrategyDraft[]> {
  return getJson<StrategyDraft[]>("/api/strategy-drafts");
}

export function saveStrategyDraft(payload: StrategyDraftPayload): Promise<StrategyDraft> {
  return postJson<StrategyDraft>("/api/strategy-drafts", payload);
}
