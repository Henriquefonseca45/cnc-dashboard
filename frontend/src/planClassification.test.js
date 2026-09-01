import test from "node:test";
import assert from "node:assert/strict";
import { PLAN_PRIORITIES, priorityLabel } from "./planClassification.js";

test("plan priorities use persisted backend values", () => {
  assert.deepEqual(PLAN_PRIORITIES.map((item) => item.value), ["normal", "medium", "high"]);
  assert.equal(priorityLabel("normal"), "NORMAL");
  assert.equal(priorityLabel("medium"), "MÉDIA");
  assert.equal(priorityLabel("high"), "ALTA");
});
