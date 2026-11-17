/**
 * Generic black-box verifier for GameSmith games.
 *
 * Every generated game exports the same five members (see contract.ts), so this
 * one breadth-first search can check any puzzle genre without knowing its rules:
 *   - interface: required exports exist and have the right shapes
 *   - purity:    applyMove never mutates the state it is given
 *   - solvable:  BFS reaches a won state from every level's initial state
 *   - difficulty: optimal move counts never decrease and the last level is harder than the first
 *
 * The harness owns this file. The agent never sees or edits it, so it cannot fake a pass.
 */
import { pathToFileURL } from "node:url";

export type Category =
  | "interface_violation"
  | "unsolvable_level"
  | "unverifiable_state_space"
  | "difficulty_not_increasing";

export interface LevelReport {
  index: number;
  solvable: boolean | null; // null = gave up at the node cap
  optimalMoves: number | null;
  statesExplored: number;
}

export interface VerifyReport {
  ok: boolean;
  category: Category | null;
  message: string;
  levels: LevelReport[];
}

export interface VerifyOptions {
  nodeCap?: number; // max states explored per level
  maxBranching?: number; // max legal moves allowed from one state
}

const MIN_LEVELS = 5;

class InterfaceError extends Error {}

function fail(category: Category, message: string, levels: LevelReport[] = []): VerifyReport {
  return { ok: false, category, message, levels };
}

function keyOf(state: unknown, where: string): string {
  let key: string | undefined;
  try {
    key = JSON.stringify(state);
  } catch (e) {
    throw new InterfaceError(`${where}: state is not JSON-serialisable (${(e as Error).message}).`);
  }
  if (key === undefined) throw new InterfaceError(`${where}: state is not JSON-serialisable.`);
  return key;
}

function call<T>(where: string, fn: () => T): T {
  try {
    return fn();
  } catch (e) {
    if (e instanceof InterfaceError) throw e;
    throw new InterfaceError(`${where} threw: ${(e as Error)?.message ?? String(e)}`);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GameModule = Record<string, any>;

function checkInterface(mod: GameModule): string | null {
  for (const fn of ["initialState", "legalMoves", "applyMove", "isWon"]) {
    if (typeof mod[fn] !== "function") return `Missing exported function \`${fn}\`.`;
  }
  if (!Array.isArray(mod.levels)) return "Missing exported array `levels`.";
  if (mod.levels.length < MIN_LEVELS) {
    return `Need at least ${MIN_LEVELS} levels, found ${mod.levels.length}.`;
  }
  return null;
}

function solveLevel(mod: GameModule, index: number, nodeCap: number, maxBranching: number): LevelReport {
  const where = `level ${index}`;
  const start = call(`${where}: initialState`, () => mod.initialState(mod.levels[index]));
  const startKey = keyOf(start, where);
  if (call(`${where}: isWon`, () => mod.isWon(start))) {
    return { index, solvable: true, optimalMoves: 0, statesExplored: 1 };
  }

  const depth = new Map<string, number>([[startKey, 0]]);
  const queue: unknown[] = [start];
  for (let head = 0; head < queue.length; head++) {
    const state = queue[head];
    const stateKey = keyOf(state, where);
    const d = depth.get(stateKey)!;

    const moves = call(`${where}: legalMoves`, () => mod.legalMoves(state));
    if (!Array.isArray(moves) || moves.some((m) => typeof m !== "string")) {
      throw new InterfaceError(`${where}: legalMoves must return string[].`);
    }
    if (moves.length > maxBranching) {
      throw new InterfaceError(`${where}: ${moves.length} legal moves from one state (max ${maxBranching}).`);
    }

    for (const move of moves) {
      const next = call(`${where}: applyMove("${move}")`, () => mod.applyMove(state, move));
      if (keyOf(state, where) !== stateKey) {
        throw new InterfaceError(`${where}: applyMove("${move}") mutated its input state; it must return a new state.`);
      }
      const nextKey = keyOf(next, where);
      if (depth.has(nextKey)) continue;
      if (call(`${where}: isWon`, () => mod.isWon(next))) {
        return { index, solvable: true, optimalMoves: d + 1, statesExplored: depth.size + 1 };
      }
      depth.set(nextKey, d + 1);
      queue.push(next);
      if (depth.size >= nodeCap) {
        return { index, solvable: null, optimalMoves: null, statesExplored: depth.size };
      }
    }
  }
  return { index, solvable: false, optimalMoves: null, statesExplored: depth.size };
}

export function verifyGame(mod: GameModule, opts: VerifyOptions = {}): VerifyReport {
  const nodeCap = opts.nodeCap ?? 200_000;
  const maxBranching = opts.maxBranching ?? 64;

  const problem = checkInterface(mod);
  if (problem) return fail("interface_violation", problem);

  const levels: LevelReport[] = [];
  try {
    for (let i = 0; i < mod.levels.length; i++) {
      levels.push(solveLevel(mod, i, nodeCap, maxBranching));
    }
  } catch (e) {
    return fail("interface_violation", (e as Error).message, levels);
  }

  const capped = levels.find((l) => l.solvable === null);
  if (capped) {
    return fail(
      "unverifiable_state_space",
      `Level ${capped.index} explored ${capped.statesExplored} states without finding a solution; keep state spaces under ${nodeCap} states.`,
      levels,
    );
  }
  const unsolvable = levels.find((l) => l.solvable === false);
  if (unsolvable) {
    return fail("unsolvable_level", `Level ${unsolvable.index} can never be won from its initial state.`, levels);
  }

  const moves = levels.map((l) => l.optimalMoves!);
  const curve = `Optimal moves per level: [${moves.join(", ")}].`;
  const trivial = levels.find((l) => l.optimalMoves === 0);
  if (trivial) {
    return fail("difficulty_not_increasing", `Level ${trivial.index} is already won at the start. ${curve}`, levels);
  }
  for (let i = 1; i < moves.length; i++) {
    if (moves[i] < moves[i - 1]) {
      return fail("difficulty_not_increasing", `Level ${i} is easier than level ${i - 1}. ${curve}`, levels);
    }
  }
  if (moves[moves.length - 1] <= moves[0]) {
    return fail("difficulty_not_increasing", `Last level is no harder than the first. ${curve}`, levels);
  }
  return { ok: true, category: null, message: `All checks passed. ${curve}`, levels };
}

async function main(): Promise<void> {
  const [modulePath, capArg] = process.argv.slice(2);
  if (!modulePath) {
    console.error("usage: node verify.js <compiled-game.js> [nodeCap]");
    process.exit(2);
  }
  let report: VerifyReport;
  try {
    const mod = await import(pathToFileURL(modulePath).href);
    report = verifyGame(mod, { nodeCap: capArg ? Number(capArg) : undefined });
  } catch (e) {
    report = fail("interface_violation", `Module failed to load: ${(e as Error).message}`);
  }
  process.stdout.write(JSON.stringify(report) + "\n");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  void main();
}
