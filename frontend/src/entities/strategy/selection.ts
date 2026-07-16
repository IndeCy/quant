import type { StrategyInstance } from "./model";

const accountStatuses = new Set(["paper", "shadow_live", "live", "active"]);

/**
 * 策略页优先展示有账户语义的实例，避免研究观察策略造成“快照缺失”的误解。
 */
export function defaultAccountStrategyInstance(instances: StrategyInstance[]): StrategyInstance | null {
  return instances.find((instance) => accountStatuses.has(instance.status)) ?? instances[0] ?? null;
}
