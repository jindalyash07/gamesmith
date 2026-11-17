/**
 * The contract every generated game must satisfy. The agent receives this file's
 * text in its system prompt; the verifier checks it at runtime.
 *
 * A game is ONE TypeScript file, `game.ts`, with no imports, exporting:
 *
 *   export const levels: Level[];                         // at least 5, ordered easy -> hard
 *   export function initialState(level: Level): State;
 *   export function legalMoves(state: State): string[];   // at most 64 moves per state
 *   export function applyMove(state: State, move: string): State;  // pure: return a NEW state
 *   export function isWon(state: State): boolean;
 *
 * Rules:
 *   - State must be plain JSON data (numbers, strings, booleans, arrays, objects).
 *   - Every level must be solvable, and need at least 1 move.
 *   - The optimal (fewest-moves) solution length must never decrease from one level
 *     to the next, and the last level must need more moves than the first.
 *   - Keep each level's reachable state space under 200,000 states.
 *   - No imports, no require, no process/globalThis/eval/Function/fetch, no timers.
 */
export interface GameContract<Level, State> {
  levels: Level[];
  initialState(level: Level): State;
  legalMoves(state: State): string[];
  applyMove(state: State, move: string): State;
  isWon(state: State): boolean;
}
