import test from "node:test";
import assert from "node:assert/strict";
import { buildMaintenanceCards, elapsedFromServer, formatElapsed } from "./maintenanceTvUtils.js";

test("cards are generated dynamically for newly registered CNCs", () => {
  const machines = [
    { id: "CNC01", status: "OCIOSA" },
    { id: "CNC08", status: "MANUTENÇÃO" },
    { id: "CNC_TESTE", status: "PARADA" },
  ];
  const calls = [{ id: 8, cncId: "CNC08", startedAt: "2026-08-04T10:00:00-03:00" }];
  const cards = buildMaintenanceCards(machines, calls);
  assert.deepEqual(cards.map((card) => card.id), ["CNC01", "CNC08"]);
  assert.equal(cards[1].maintenance.id, 8);
});

test("elapsed counter derives from persisted startedAt and server clock after reload", () => {
  const startedAt = "2026-08-04T10:00:00-03:00";
  const clientNow = Date.parse("2026-08-04T10:30:00-03:00");
  assert.equal(formatElapsed(elapsedFromServer(startedAt, 17_000, clientNow)), "00:30:17");
});

test("machines without maintenance receive no zero counter source", () => {
  const [card] = buildMaintenanceCards([{ id: "CNC01", status: "OCIOSA" }], []);
  assert.equal(card.maintenance, null);
});
