import { getJson } from "../../shared/api/client";
import type { ResearchTodos } from "./model";

export function getResearchTodos(): Promise<ResearchTodos> {
  return getJson<ResearchTodos>("/api/research/todos");
}
