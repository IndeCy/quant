import { describe, expect, it } from "vitest";

import { ackStatusTone } from "./ackStatus";

describe("operations acknowledgement status helpers", () => {
  it("maps acknowledgement status to dashboard tone", () => {
    expect(ackStatusTone("ACKNOWLEDGED")).toBe("success");
    expect(ackStatusTone("RESOLVED")).toBe("success");
    expect(ackStatusTone("UNKNOWN")).toBe("neutral");
  });
});
