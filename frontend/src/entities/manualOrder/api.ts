import { getJson, postJson } from "../../shared/api/client";
import type { ManualOrder, ManualOrderBatch } from "./model";

export function getManualOrderBatch(strategyId: string): Promise<ManualOrderBatch> {
  return getJson<ManualOrderBatch>(`/api/manual-orders/${strategyId}`);
}

export function createManualOrdersFromAccount(strategyId: string): Promise<ManualOrderBatch> {
  return postJson<ManualOrderBatch>(`/api/manual-orders/from-account/${strategyId}`, {});
}

export function confirmManualOrderBatch(batchId: string): Promise<ManualOrderBatch> {
  return postJson<ManualOrderBatch>(`/api/manual-orders/batches/${batchId}/confirm`, {});
}

export function fillManualOrder(orderId: string, filledQuantity: number, filledPrice: number): Promise<ManualOrder> {
  return postJson<ManualOrder>(`/api/manual-orders/orders/${orderId}/fill`, {
    filled_quantity: filledQuantity,
    filled_price: filledPrice
  });
}

export function rejectManualOrder(orderId: string, reason: string): Promise<ManualOrder> {
  return postJson<ManualOrder>(`/api/manual-orders/orders/${orderId}/reject`, { reason });
}
