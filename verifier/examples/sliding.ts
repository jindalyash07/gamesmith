// Reference game: 3x3 sliding-tile puzzle. Moves name the direction the blank (0) travels.
type State = { board: number[] };
type Level = number[];

const GOAL = [1, 2, 3, 4, 5, 6, 7, 8, 0];
const DIRS: Record<string, [number, number]> = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] };

// @levels-start
export const levels: Level[] = [
  [1, 2, 3, 4, 0, 6, 7, 5, 8],
  [1, 2, 3, 4, 8, 0, 7, 6, 5],
  [2, 8, 3, 1, 5, 0, 4, 7, 6],
  [1, 2, 3, 5, 7, 0, 8, 6, 4],
  [1, 3, 6, 0, 2, 7, 5, 8, 4],
  [2, 1, 8, 3, 5, 6, 4, 0, 7],
];
// @levels-end
// @unsolvable-level: [2, 1, 3, 4, 5, 6, 7, 8, 0]

export function initialState(level: Level): State {
  return { board: [...level] };
}

export function legalMoves(state: State): string[] {
  const z = state.board.indexOf(0);
  const r = Math.floor(z / 3);
  const c = z % 3;
  return Object.keys(DIRS).filter((d) => {
    const [dr, dc] = DIRS[d];
    return r + dr >= 0 && r + dr < 3 && c + dc >= 0 && c + dc < 3;
  });
}

export function applyMove(state: State, move: string): State {
  const board = [...state.board];
  const z = board.indexOf(0);
  const [dr, dc] = DIRS[move];
  const n = (Math.floor(z / 3) + dr) * 3 + (z % 3) + dc;
  [board[z], board[n]] = [board[n], board[z]];
  return { board };
}

export function isWon(state: State): boolean {
  return state.board.every((v, i) => v === GOAL[i]);
}
