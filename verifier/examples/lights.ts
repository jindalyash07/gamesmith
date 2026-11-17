// Reference game: 3x3 Lights Out. Pressing a cell toggles it and its orthogonal neighbours.
type State = { grid: number[] };
type Level = number[];

// @levels-start
export const levels: Level[] = [
  [1, 0, 0, 1, 1, 0, 1, 0, 0],
  [0, 1, 1, 0, 0, 0, 0, 1, 1],
  [0, 0, 1, 0, 0, 0, 1, 0, 1],
  [1, 0, 1, 1, 0, 0, 0, 1, 0],
  [0, 0, 0, 0, 1, 0, 0, 0, 0],
  [0, 1, 1, 0, 1, 0, 0, 1, 1],
];
// @levels-end
// @unsolvable-level: [2, 0, 0, 0, 0, 0, 0, 0, 0]

export function initialState(level: Level): State {
  return { grid: [...level] };
}

export function legalMoves(_state: State): string[] {
  return ["p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"];
}

export function applyMove(state: State, move: string): State {
  const grid = [...state.grid];
  const i = Number(move.slice(1));
  const r = Math.floor(i / 3);
  const c = i % 3;
  for (const [dr, dc] of [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]]) {
    const nr = r + dr;
    const nc = c + dc;
    if (nr >= 0 && nr < 3 && nc >= 0 && nc < 3) grid[nr * 3 + nc] = 1 - grid[nr * 3 + nc];
  }
  return { grid };
}

export function isWon(state: State): boolean {
  return state.grid.every((v) => v === 0);
}
