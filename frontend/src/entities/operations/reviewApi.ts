import { getJson } from "../../shared/api/client";
import type { OperationsReview } from "./reviewModel";

export function getOperationsReview(): Promise<OperationsReview> {
  return getJson<OperationsReview>("/api/operations/review");
}
