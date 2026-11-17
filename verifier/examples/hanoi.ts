// Reference game: Tower of Hanoi. Move every disk to the goal peg; never place a larger disk on a smaller one.
type Level = { disks: number; goalPeg: number };
type State = { pegs: number[][]; goalPeg: number };

// @levels-start
export const levels: Level[] = [
  { disks: 2, goalPeg: 2 },
  { disks: 3, goalPeg: 2 },
  { disks: 4, goalPeg: 2 },
  { disks: 5, goalPeg: 2 },
  { disks: 6, goalPeg: 2 },
  { disks: 7, goalPeg: 2 },
];
// @levels-end
// @unsolvable-level: { disks: 3, goalPeg: 5 }

export function initialState(level: Level): State {
  const tower: number[] = [];
  for (let d = level.disks; d >= 1; d--) tower.push(d);
  return { pegs: [tower, [], []], goalPeg: level.goalPeg };
}

export function legalMoves(state: State): string[] {
  const moves: string[] = [];
  for (let from = 0; from < 3; from++) {
    const disk = state.pegs[from][state.pegs[from].length - 1];
    if (disk === undefined) continue;
    for (let to = 0; to < 3; to++) {
      if (to === from) continue;
      const top = state.pegs[to][state.pegs[to].length - 1];
      if (top === undefined || top > disk) moves.push(`${from}>${to}`);
    }
  }
  return moves;
}

export function applyMove(state: State, move: string): State {
  const [from, to] = move.split(">").map(Number);
  const pegs = state.pegs.map((p) => [...p]);
  pegs[to].push(pegs[from].pop()!);
  return { pegs, goalPeg: state.goalPeg };
}

export function isWon(state: State): boolean {
  const others = state.pegs.filter((_, i) => i !== state.goalPeg);
  return state.goalPeg >= 0 && state.goalPeg < 3 && others.every((p) => p.length === 0);
}
