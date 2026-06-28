import type { FactorDefinition } from "../factor/model";

export interface StrategyDraftFactor extends FactorDefinition {
  weight: number;
  transform: string;
  enabled: boolean;
}

export interface StrategyDraft {
  draft_id: string;
  name: string;
  status: "draft";
  description: string;
  config: Record<string, string | number | boolean>;
  factors: StrategyDraftFactor[];
}

export interface StrategyDraftPayload {
  draft_id: string;
  name: string;
  description: string;
  config: Record<string, string | number | boolean>;
  factors: Array<{
    factor_id: string;
    weight: number;
    transform: string;
    enabled: boolean;
  }>;
}
