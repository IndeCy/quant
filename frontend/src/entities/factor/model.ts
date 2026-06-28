export interface FactorDefinition {
  factor_id: string;
  name: string;
  category: string;
  direction: string;
  source?: string;
  description?: string;
  enabled: boolean;
  weight?: number;
  transform?: string;
}
