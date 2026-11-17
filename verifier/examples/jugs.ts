// Reference game: water jugs. Fill, empty or pour between two jugs until one holds the target amount.
type Level = { capA: number; capB: number; target: number };
type State = Level & { a: number; b: number };

// @levels-start
export const levels: Level[] = [
  { capA: 2, capB: 3, target: 1 },
  { capA: 2, capB: 5, target: 1 },
  { capA: 2, capB: 9, target: 1 },
  { capA: 3, capB: 14, target: 7 },
  { capA: 7, capB: 15, target: 11 },
  { capA: 13, capB: 15, target: 14 },
];
// @levels-end
// @unsolvable-level: { capA: 2, capB: 4, target: 3 }

export function initialState(level: Level): State {
  return { ...level, a: 0, b: 0 };
}

export function legalMoves(_state: State): string[] {
  return ["fillA", "fillB", "emptyA", "emptyB", "pourAB", "pourBA"];
}

export function applyMove(state: State, move: string): State {
  const s = { ...state };
  if (move === "fillA") s.a = s.capA;
  else if (move === "fillB") s.b = s.capB;
  else if (move === "emptyA") s.a = 0;
  else if (move === "emptyB") s.b = 0;
  else if (move === "pourAB") {
    const p = Math.min(s.a, s.capB - s.b);
    s.a -= p;
    s.b += p;
  } else if (move === "pourBA") {
    const p = Math.min(s.b, s.capA - s.a);
    s.b -= p;
    s.a += p;
  }
  return s;
}

export function isWon(state: State): boolean {
  return state.a === state.target || state.b === state.target;
}
