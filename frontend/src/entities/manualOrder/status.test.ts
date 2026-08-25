import { expect, test } from "vitest";

import { manualOrderStatusTone, orderSideLabel } from "./status";

test("manualOrderStatusTone maps lifecycle statuses", () => {
  expect(manualOrderStatusTone("DRAFT")).toBe("warning");
  expect(manualOrderStatusTone("CONFIRMED")).toBe("success");
  expect(manualOrderStatusTone("REJECTED")).toBe("danger");
});

test("orderSideLabel translates buy and sell", () => {
  expect(orderSideLabel("BUY")).toBe("买入");
  expect(orderSideLabel("SELL")).toBe("卖出");
});
