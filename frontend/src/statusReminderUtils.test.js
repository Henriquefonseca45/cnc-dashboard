import test from "node:test";
import assert from "node:assert/strict";
import { formatReminderDuration, getStatusReminder } from "./statusReminderUtils.js";

const NOW = Date.parse("2026-08-28T12:00:00-03:00");

test("does not remind for powered off machines", () => {
  assert.equal(getStatusReminder({ status: "DESLIGADA", statusSince: "2026-08-28T08:00:00-03:00", nowMs: NOW }), null);
});

test("reminds after the threshold for stopped statuses", () => {
  assert.equal(getStatusReminder({ status: "REFEIÇÃO", statusSince: "2026-08-28T11:01:00-03:00", nowMs: NOW }), null);
  const reminder = getStatusReminder({ status: "REFEIÇÃO", statusSince: "2026-08-28T10:59:00-03:00", nowMs: NOW });
  assert.equal(reminder.kind, "status-stale");
  assert.equal(reminder.limitMinutes, 60);
});

test("reminds when machining estimated time ends", () => {
  assert.equal(getStatusReminder({ status: "USINANDO", remainingSeconds: 1, hasExecutingFile: true }), null);
  assert.equal(getStatusReminder({ status: "USINANDO", remainingSeconds: 0, hasExecutingFile: true }).kind, "estimated-finished");
});

test("formats reminder duration for the operator", () => {
  assert.equal(formatReminderDuration(15 * 60), "15 min");
  assert.equal(formatReminderDuration(75 * 60), "1h 15min");
});

