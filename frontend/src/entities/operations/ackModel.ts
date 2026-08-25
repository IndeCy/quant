export type OperationsAckStatus = "ACKNOWLEDGED" | "RESOLVED";

export interface OperationsAcknowledgement {
  ack_id: string;
  trade_date: string;
  source: string;
  category: string;
  name: string;
  severity: string;
  decision: string;
  message: string;
  resolution: string;
  operator: string;
  status: OperationsAckStatus;
  created_at: string;
  modified_at: string;
}

export interface OperationsAckPayload {
  trade_date: string;
  source: string;
  category: string;
  name: string;
  severity: string;
  decision: string;
  message: string;
  resolution: string;
  operator: string;
}
