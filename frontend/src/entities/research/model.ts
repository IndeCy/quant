export interface ResearchTodos {
  title: string;
  path: string;
  content: string;
  missing: boolean;
}

export interface FactorIdea {
  idea_id: string;
  title: string;
  raw_description: string;
  source: string;
  hypothesis: string;
  required_data: string[];
  as_of_requirement: string;
  direction: string;
  status: string;
  created_at?: string;
  modified_at?: string;
}

export interface StrategyIdea {
  idea_id: string;
  title: string;
  raw_description: string;
  source: string;
  hypothesis: string;
  candidate_template: string;
  required_factors: string[];
  status: string;
  created_at?: string;
  modified_at?: string;
}
