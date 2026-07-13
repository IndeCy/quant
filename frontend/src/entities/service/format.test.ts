import { describe, expect, it } from "vitest";

import { formatCommand } from "./format";

describe("formatCommand", () => {
  it("joins command arguments for display", () => {
    expect(formatCommand(["python", "-m", "api.local_server"])).toBe("python -m api.local_server");
  });
});
