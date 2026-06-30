import { getJson, postJson } from "../../shared/api/client";
import type { FactorIdea, ResearchTodos, StrategyIdea } from "./model";

export function getResearchTodos(): Promise<ResearchTodos> {
  return getJson<ResearchTodos>("/api/research/todos");
}

export function listFactorIdeas(): Promise<FactorIdea[]> {
  return getJson<FactorIdea[]>("/api/research/factor-ideas");
}

export function saveFactorIdea(payload: FactorIdea): Promise<FactorIdea> {
  return postJson<FactorIdea>("/api/research/factor-ideas", payload);
}

export function listStrategyIdeas(): Promise<StrategyIdea[]> {
  return getJson<StrategyIdea[]>("/api/research/strategy-ideas");
}

export function saveStrategyIdea(payload: StrategyIdea): Promise<StrategyIdea> {
  return postJson<StrategyIdea>("/api/research/strategy-ideas", payload);
}
