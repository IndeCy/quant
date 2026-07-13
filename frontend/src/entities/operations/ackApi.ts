import { getJson, postJson } from "../../shared/api/client";
import type { OperationsAcknowledgement, OperationsAckPayload } from "./ackModel";

export function listOperationsAcknowledgements(): Promise<OperationsAcknowledgement[]> {
  return getJson<OperationsAcknowledgement[]>("/api/operations/acknowledgements");
}

export function recordOperationsAcknowledgement(payload: OperationsAckPayload): Promise<OperationsAcknowledgement> {
  return postJson<OperationsAcknowledgement>("/api/operations/acknowledgements", payload);
}
