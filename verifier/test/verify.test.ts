import { test } from "node:test";
import assert from "node:assert/strict";
import { verifyGame } from "../src/verify.js";
import * as sliding from "../examples/sliding.js";
import * as lights from "../examples/lights.js";
import * as hanoi from "../examples/hanoi.js";
import * as jugs from "../examples/jugs.js";

const examples = { sliding, lights, hanoi, jugs };

for (const [name, game] of Object.entries(examples)) {
  test(`reference game "${name}" passes every check`, () => {
    const report = verifyGame(game);
    assert.equal(report.ok, true, report.message);
    assert.equal(report.levels.length, game.levels.length);
  });
}

test("Tower of Hanoi optimal moves are 2^n - 1", () => {
  const report = verifyGame(hanoi);
  assert.deepEqual(report.levels.map((l) => l.optimalMoves), [3, 7, 15, 31, 63, 127]);
});

test("missing export is an interface violation", () => {
  const { isWon: _drop, ...rest } = sliding;
  const report = verifyGame(rest);
  assert.equal(report.category, "interface_violation");
  assert.match(report.message, /isWon/);
});

test("too few levels is an interface violation", () => {
  const report = verifyGame({ ...sliding, levels: sliding.levels.slice(0, 3) });
  assert.equal(report.category, "interface_violation");
});

test("unsolvable level is detected", () => {
  const levels = [...sliding.levels.slice(0, 5), [2, 1, 3, 4, 5, 6, 7, 8, 0]];
  const report = verifyGame({ ...sliding, levels });
  assert.equal(report.category, "unsolvable_level");
  assert.match(report.message, /Level 5/);
});

test("decreasing difficulty is detected", () => {
  const report = verifyGame({ ...sliding, levels: [...sliding.levels].reverse() });
  assert.equal(report.category, "difficulty_not_increasing");
});

test("already-won level is rejected", () => {
  const levels = [[1, 2, 3, 4, 5, 6, 7, 8, 0], ...sliding.levels.slice(1)];
  const report = verifyGame({ ...sliding, levels });
  assert.equal(report.category, "difficulty_not_increasing");
});

test("mutating applyMove is caught", () => {
  const impure = {
    ...sliding,
    applyMove: (s: { board: number[] }, m: string) => {
      const next = sliding.applyMove(s, m);
      s.board.reverse();
      return next;
    },
  };
  const report = verifyGame(impure);
  assert.equal(report.category, "interface_violation");
  assert.match(report.message, /mutated/);
});

test("node cap turns a huge state space into unverifiable", () => {
  const report = verifyGame(hanoi, { nodeCap: 50 });
  assert.equal(report.category, "unverifiable_state_space");
});

test("exceptions inside game code are reported, not thrown", () => {
  const broken = { ...jugs, legalMoves: () => { throw new Error("boom"); } };
  const report = verifyGame(broken);
  assert.equal(report.category, "interface_violation");
  assert.match(report.message, /boom/);
});
