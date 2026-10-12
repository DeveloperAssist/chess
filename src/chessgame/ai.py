"""The computer player: minimax search with alpha-beta pruning.

How it thinks, in four ideas:

1. ``evaluate`` gives a position a score in centipawns (100 = one pawn): material, plus small
   bonuses for good squares (knights in the centre, pawns moving up, a castled king...).
2. Minimax: try every move, then every reply, and so on to a fixed depth, assuming both sides
   always pick their best move. We write it as *negamax*: my score is minus your score.
3. Alpha-beta: stop looking at a move as soon as we know it is worse than one we already have.
   Same answer as plain minimax, many times fewer positions.
4. Quiescence: at the end of the search, keep following captures, so the computer does not stop
   thinking in the middle of a queen trade and think it is a queen up.
"""

import random
import threading
import time
from dataclasses import dataclass

from .board import BLACK, EMPTY, WHITE, Board, Move, other
from .openings import book_move

# --- Evaluation -------------------------------------------------------------------------------

VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
MATE = 100_000
INFINITY = 1_000_000


def _centre(row: int, col: int) -> int:
    """0 on the edge of the board, up to 3 on the four centre squares."""
    return 3 - int(max(abs(row - 3.5), abs(col - 3.5)))


def _pawn(row: int, col: int) -> int:
    if row in (0, 7):
        return 0
    bonus = (6 - row) * 6  # every step forward is worth a little
    if col in (3, 4):  # d- and e-pawns: get them into the centre
        bonus += 15 if row in (3, 4) else -10 if row == 6 else 0
    return bonus


def _king_middlegame(row: int, col: int) -> int:
    if row == 7:  # the back rank, where a castled king hides
        return 25 if col in (1, 2, 6) else 10 if col in (0, 7) else -5
    return -15 * min(7 - row, 4)  # a king walking up the board early gets hunted


# Bonus tables from White's point of view (row 0 = rank 8). Black uses the same tables flipped.
TABLES = {
    "p": [_pawn(*divmod(s, 8)) for s in range(64)],
    "n": [12 * _centre(*divmod(s, 8)) - 20 for s in range(64)],
    "b": [6 * _centre(*divmod(s, 8)) - 6 for s in range(64)],
    "r": [15 if s // 8 == 1 else 5 if s in (59, 60) else 0 for s in range(64)],
    "q": [3 * _centre(*divmod(s, 8)) - 5 for s in range(64)],
    "k": [_king_middlegame(*divmod(s, 8)) for s in range(64)],
}
KING_ENDGAME = [10 * _centre(*divmod(s, 8)) - 15 for s in range(64)]  # in the endgame: centralise


def evaluate(board: Board) -> int:
    """The position's score for the side to move, in centipawns."""
    squares = board.squares
    big_pieces = sum(VALUES[p.lower()] for p in squares if p not in "PpKk.")
    endgame = big_pieces <= 1500
    king_table = KING_ENDGAME if endgame else TABLES["k"]
    score = material = 0
    bishops = {True: 0, False: 0}
    for s, p in enumerate(squares):
        if p == EMPTY:
            continue
        kind = p.lower()
        white = p.isupper()
        spot = s if white else s ^ 56  # s ^ 56 flips the row: a black piece on e5 scores like e4
        value = VALUES[kind] + (king_table[spot] if kind == "k" else TABLES[kind][spot])
        score += value if white else -value
        material += VALUES[kind] if white else -VALUES[kind]
        if kind == "b":
            bishops[white] += 1
    score += 30 * ((bishops[True] >= 2) - (bishops[False] >= 2))  # the bishop pair
    if endgame and abs(material) >= 400:
        score += _mop_up(board, winner=WHITE if material > 0 else BLACK)
    return score if board.turn == WHITE else -score


def _mop_up(board: Board, winner: str) -> int:
    """A rook or more ahead in the endgame: drive the losing king to the edge of the board and
    bring our king closer. Without this, the computer can't mate with king and queen against a
    lone king: every square looks equally good, so it wanders until the game is drawn."""
    loser_row, loser_col = divmod(board.kings[other(winner)], 8)
    winner_row, winner_col = divmod(board.kings[winner], 8)
    to_edge = max(3 - loser_row, loser_row - 4) + max(3 - loser_col, loser_col - 4)  # 0 to 6
    closeness = 14 - abs(loser_row - winner_row) - abs(loser_col - winner_col)
    bonus = 10 * to_edge + 4 * closeness
    return bonus if winner == WHITE else -bonus


# --- Search -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Level:
    name: str
    depth: int  # how far ahead it looks, in half-moves (one move by one side = 1)
    seconds: float  # time limit: it stops early if a depth takes too long
    noise: int  # random centipawns added to each move's score, so weaker levels make mistakes
    quiescence: bool  # follow captures at the end of the search


LEVELS = {
    "easy": Level("Easy", depth=1, seconds=1.0, noise=50, quiescence=False),
    "medium": Level("Medium", depth=2, seconds=2.0, noise=0, quiescence=True),
    "hard": Level("Hard", depth=5, seconds=3.0, noise=0, quiescence=True),
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    move: Move
    score: int  # centipawns for the side that moves, MATE - n when it sees a mate
    depth: int
    nodes: int  # positions looked at
    seconds: float
    book: bool = False  # True when the move came from the opening book (no thinking needed)


class SearchStopped(Exception):
    """Raised inside the search when time is up or the player pressed undo or new game."""


def choose_move(
    board: Board,
    level: str | Level = "medium",
    stop: threading.Event | None = None,
    seen: set[str] | None = None,
    seed: int | None = None,
    book: bool = True,
) -> SearchResult | None:
    """Pick a move for the side to move. Returns None if there are no legal moves.

    While the position is in the opening book (and ``book`` is True), it plays a book move: real
    openings, picked at random with the popular lines more often. After that, it searches.

    ``seen`` holds the positions (``Board.position_key``) already played in this game. Like real
    engines, the search scores a return to one of them as a draw. So a winning computer makes
    progress instead of going round in circles, and a losing one looks for a repetition.
    """
    level = LEVELS[level] if isinstance(level, str) else level
    rng = random.Random(seed)
    if book and (move := book_move(board, rng)) is not None:
        return SearchResult(move, 0, 0, 0, 0.0, book=True)
    return _Searcher(board.copy(), level, stop, seen or set(), rng).run()


class _Searcher:
    def __init__(
        self,
        board: Board,
        level: Level,
        stop: threading.Event | None,
        seen: set[str],
        rng: random.Random,
    ) -> None:
        self.board = board  # our own copy: the search makes and unmakes thousands of moves on it
        self.level = level
        self.stop = stop
        self.seen = seen
        self.rng = rng
        self.nodes = 0
        self.started = time.perf_counter()
        self.deadline = self.started + level.seconds

    def run(self) -> SearchResult | None:
        moves = self.board.legal_moves()
        if not moves:
            return None
        self.rng.shuffle(moves)  # so equal moves are picked in a different order each game
        moves.sort(key=self._order, reverse=True)

        best, best_score, depth_done = moves[0], -INFINITY, 0
        for depth in range(1, self.level.depth + 1):  # iterative deepening: 1 move ahead, then 2...
            try:
                move, score = self._root(moves, depth)
            except SearchStopped:
                break
            best, best_score, depth_done = move, score, depth
            if abs(score) >= MATE - 100:  # found a forced mate: no need to look deeper
                break
            moves.remove(move)
            moves.insert(0, move)  # search the best move first next time: more pruning
        seconds = time.perf_counter() - self.started
        score = best_score if depth_done else 0  # stopped before even one depth finished
        return SearchResult(best, score, depth_done, self.nodes, seconds)

    def _root(self, moves: list[Move], depth: int) -> tuple[Move, int]:
        board = self.board
        alpha = -INFINITY
        best, best_score = moves[0], -INFINITY
        for move in moves:
            board.make(move)
            if self.level.noise:
                # Weaker levels score every move exactly, then add a little randomness.
                score = -self._negamax(depth - 1, -INFINITY, INFINITY, 1)
                score += self.rng.randint(-self.level.noise, self.level.noise)
            else:
                score = -self._negamax(depth - 1, -INFINITY, -alpha, 1)
            board.unmake()
            if score > best_score:
                best, best_score = move, score
            alpha = max(alpha, score)
        return best, best_score

    def _negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        self._tick()
        board = self.board
        if board.halfmove >= 100:
            return 0
        if ply <= 2 and board.position_key() in self.seen:
            return 0  # back to a position from the game: count it as a draw (checked near the root only)
        if depth == 0:
            return self._quiesce(alpha, beta) if self.level.quiescence else evaluate(board)

        mover, them = board.turn, other(board.turn)
        any_legal = False
        for move in sorted(board.pseudo_moves(), key=self._order, reverse=True):
            board.make(move)
            if board.is_attacked(board.kings[mover], them):  # illegal: our king would be in check
                board.unmake()
                continue
            any_legal = True
            score = -self._negamax(depth - 1, -beta, -alpha, ply + 1)
            board.unmake()
            if score >= beta:
                return beta  # the opponent will never allow this line: stop here (a "cut-off")
            alpha = max(alpha, score)
        if not any_legal:
            # Checkmate (a quicker mate scores higher) or stalemate.
            return -(MATE - ply) if board.in_check() else 0
        return alpha

    def _quiesce(self, alpha: int, beta: int) -> int:
        """Search only captures and promotions until the position is quiet."""
        self._tick()
        board = self.board
        stand_pat = evaluate(board)  # we may also choose not to capture anything
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
        mover, them = board.turn, other(board.turn)
        loud = [m for m in board.pseudo_moves() if m.promotion or board.squares[m.end] != EMPTY]
        for move in sorted(loud, key=self._order, reverse=True):
            board.make(move)
            if board.is_attacked(board.kings[mover], them):
                board.unmake()
                continue
            score = -self._quiesce(-beta, -alpha)
            board.unmake()
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha

    def _order(self, move: Move) -> int:
        """Try likely-good moves first: alpha-beta prunes far more when the best move comes early.
        Captures go first, biggest victim with the smallest attacker ("MVV-LVA")."""
        squares = self.board.squares
        victim = squares[move.end]
        score = 0
        if victim != EMPTY:
            score += 10 * VALUES[victim.lower()] - VALUES[squares[move.start].lower()] + 1000
        if move.promotion:
            score += VALUES[move.promotion] + 1000
        return score

    def _tick(self) -> None:
        self.nodes += 1
        if self.nodes % 512 == 0 and (
            time.perf_counter() > self.deadline or (self.stop is not None and self.stop.is_set())
        ):
            raise SearchStopped
