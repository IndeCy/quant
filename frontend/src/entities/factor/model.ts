export interface FactorDefinition {
  factor_id: string;
  name: string;
  category: string;
  direction: string;
  source?: string;
  description?: string;
  enabled: boolean;
  config?: Record<string, string | number | boolean>;
  weight?: number;
  transform?: string;
  strategies?: FactorStrategyUsage[];
}

export interface FactorStrategyUsage {
  strategy_id: string;
  name: string;
  status: string;
  weight: number;
  transform: string;
  enabled: boolean;
}
