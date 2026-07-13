import { getJson } from "../../shared/api/client";
import type { AccountSnapshot } from "./model";

export function getAccountSnapshot(strategyId: string): Promise<AccountSnapshot> {
  return getJson<AccountSnapshot>(`/api/accounts/${strategyId}`);
}
