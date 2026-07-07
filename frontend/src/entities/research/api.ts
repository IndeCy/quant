import { getJson, postJson } from "../../shared/api/client";
import type {
  FactorIdea,
  HotMoneyLeaderView,
  OpportunityRanking,
  OpportunityStock,
  OpportunityTheme,
  ResearchNote,
  ResearchTodos,
  StrategyIdea
} from "./model";

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

export function listResearchNotes(): Promise<ResearchNote[]> {
  return getJson<ResearchNote[]>("/api/research/notes");
}

export function getResearchNote(noteId: string): Promise<ResearchNote> {
  return getJson<ResearchNote>(`/api/research/notes/${encodeURIComponent(noteId)}`);
}

export function saveResearchNote(payload: ResearchNote): Promise<ResearchNote> {
  return postJson<ResearchNote>("/api/research/notes", payload);
}

export function listOpportunityThemes(): Promise<OpportunityTheme[]> {
  return getJson<OpportunityTheme[]>("/api/research/opportunities");
}

export function listOpportunityRankings(): Promise<OpportunityRanking[]> {
  return getJson<OpportunityRanking[]>("/api/research/opportunity-rankings");
}

export function getHotMoneyLeaders(): Promise<HotMoneyLeaderView> {
  return getJson<HotMoneyLeaderView>("/api/research/hot-money-leaders");
}

export function saveOpportunityTheme(payload: OpportunityTheme): Promise<OpportunityTheme> {
  return postJson<OpportunityTheme>("/api/research/opportunities", payload);
}

export function saveOpportunityStock(payload: OpportunityStock): Promise<OpportunityStock> {
  return postJson<OpportunityStock>("/api/research/opportunity-stocks", payload);
}
