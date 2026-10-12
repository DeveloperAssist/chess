"""The coach's engine room: analyse positions, grade every move, and review a whole game.

How a move is graded
--------------------
1. Analyse the position before the move: the best move and its score (depth 3).
2. Score the move that was played: analyse the position after it from the opponent's side, one
   half-move shallower, so both scores look the same distance ahead.
3. Turn both scores into an *expected result* between 0 (lost) and 1 (won), the way Lichess does,
   and compare. Losing 0.02 of a point is nothing; losing 0.20 is a blunder.

A centipawn means much more in a level game than when you're already a queen up. Expected results
take care of that: being +9 or +12 is the same "winning".
"""

import math
import threading
from collections import Counter
from dataclasses import dataclass

from .ai import MATE, Level, choose_move
from .board import EMPTY, WHITE, Board, Move
from .game import Game
from .notation import san
from .openings import get_book

ANALYSIS = Level("Analysis", depth=3, seconds=2.0, noise=0, quiescence=True)
REPLY = Level("Reply", depth=2, seconds=1.0, noise=0, quiescence=True)

KINDS = ("book", "best", "excellent", "good", "inaccuracy", "mistake", "miss", "blunder")
LABELS = {
    "book": "Book move",
    "best": "Best move",
    "excellent": "Excellent",
    "good": "Good move",
    "inaccuracy": "Inaccuracy",
    "mistake": "Mistake",
    "miss": "Missed chance",
    "blunder": "Blunder",
}
SUFFIX = {"inaccuracy": "?!", "mistake": "?", "miss": "?", "blunder": "??"}
BAD = ("inaccuracy", "mistake", "miss", "blunder")


@dataclass(frozen=True, slots=True)
class Analysis:
    best: Move | None  # None when the game is over in this position
    score: int  # centipawns for the side to move; MATE - n means it mates in n half-moves
    depth: int


def analyse(board: Board, level: Level = ANALYSIS, stop: threading.Event | None = None) -> Analysis:
    if board.insufficient_material():
        return Analysis(None, 0, 0)
    result = choose_move(board, level, stop=stop, seed=0, book=False)
    if result is None:  # checkmate or stalemate
        return Analysis(None, -MATE if board.in_check() else 0, 0)
    return Analysis(result.move, result.score, result.depth)


def expected(score: int) -> float:
    """The expected result (0 = loss, 0.5 = draw, 1 = win) for a score in centipawns."""
    if score >= MATE - 1000:
        return 1.0
    if score <= -(MATE - 1000):
        return 0.0
    return 1 / (1 + math.exp(-0.00368208 * score))


def mate_in(score: int) -> int | None:
    """3 for 'mates in 3', -2 for 'gets mated in 2', None if the score is not a mate."""
    if abs(score) < MATE - 1000:
        return None
    moves = (MATE - abs(score) + 1) // 2
    return moves if score > 0 else -moves


def format_score(white_score: int) -> str:
    """A score from White's point of view, as people write it: '+1.2', '-0.4', 'M3', '-M2'."""
    mate = mate_in(white_score)
    if mate is not None:
        return f"{'-' if mate < 0 else ''}M{abs(mate)}" if mate else "#"
    return f"{white_score / 100:+.1f}"


def grade(best_score: int, played_score: int, is_best: bool, is_book: bool) -> tuple[str, float]:
    """The kind of move ('best', 'blunder', ...) and how much of a point it threw away."""
    if is_book:
        return "book", 0.0
    best, played = expected(best_score), expected(played_score)
    loss = max(0.0, best - played)
    if is_best or loss < 0.005:
        return "best", loss
    if loss < 0.02:
        return "excellent", loss
    if loss < 0.05:
        return "good", loss
    if loss < 0.10:
        return "inaccuracy", loss
    if best >= 0.70 and played >= 0.35:
        return "miss", loss  # you had a winning move and let most of it go
    if loss < 0.20:
        return "mistake", loss
    return "blunder", loss


def move_accuracy(loss: float) -> float:
    """Lichess's formula: 100% for a perfect move, falling quickly as the move loses more."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss * 100) - 3.1669))


@dataclass(frozen=True, slots=True)
class MoveReview:
    ply: int  # 0 is White's first move
    color: str  # who played it
    move: Move
    san: str
    kind: str  # one of KINDS
    loss: float  # expected result thrown away, 0 to 1
    best: Move | None
    best_san: str
    best_score: int  # for the player, before the move
    played_score: int  # for the player, after the move
    reply: Move | None  # the opponent's best answer to the played move
    reply_san: str
    fen_before: str
    fen_after: str
    last_capture: int | None = None  # where the opponent's previous move captured, if it did
    last_taken: str | None = None  # and the kind of piece it took there ('p', 'n', ...)

    @property
    def accuracy(self) -> float:
        return 100.0 if self.kind == "book" else move_accuracy(self.loss)

    @property
    def label(self) -> str:
        return LABELS[self.kind]


class AnalysisCache:
    """Remembers every analysis by position, so nothing is worked out twice."""

    def __init__(self) -> None:
        self._results: dict[tuple[str, str], Analysis] = {}

    @staticmethod
    def _key(fen: str, level: Level) -> tuple[str, str]:
        return Board(fen).position_key(), level.name

    def get(self, fen: str, level: Level = ANALYSIS) -> Analysis | None:
        return self._results.get(self._key(fen, level))

    def compute(self, fen: str, level: Level = ANALYSIS, stop: threading.Event | None = None) -> Analysis:
        key = self._key(fen, level)
        if key not in self._results:
            result = analyse(Board(fen), level, stop)
            if stop is not None and stop.is_set():
                return result  # cut short: don't keep a half-finished answer
            self._results[key] = result
        return self._results[key]


def jobs_for(game: Game, levels: tuple[Level, Level] = (ANALYSIS, REPLY)) -> list[tuple[str, Level]]:
    """What to analyse for a game, most urgent first: the current position, then the last move,
    then every earlier move."""
    position, reply = levels
    fens = game.fens
    jobs = [(fens[-1], position)]
    for i in range(len(game.moves) - 1, -1, -1):
        jobs += [(fens[i], position), (fens[i + 1], reply)]
    return jobs


def review_move(game: Game, ply: int, cache: AnalysisCache, levels=(ANALYSIS, REPLY)) -> MoveReview | None:
    """Grade one move from what's in the cache (None if the analysis isn't there yet)."""
    position, reply_level = levels
    fen_before, fen_after = game.fens[ply], game.fens[ply + 1]
    board = Board(fen_before)
    move = game.moves[ply]
    before = cache.get(fen_before, position)
    after = cache.get(fen_after, reply_level)
    is_book = get_book().is_book(board, move)
    if before is None or (after is None and move != before.best and not is_book):
        return None
    if move == before.best:
        played_score = before.score
    elif after is not None:
        played_score = -after.score
    else:
        played_score = before.score  # a book move whose reply isn't analysed yet
    kind, loss = grade(before.score, played_score, move == before.best, is_book)
    best_san = san(board, before.best) if before.best else ""
    reply = after.best if after else None
    reply_san = san(Board(fen_after), reply) if reply else ""
    last_capture = last_taken = None
    if ply > 0 and "x" in game.sans[ply - 1]:
        previous = Board(game.fens[ply - 1])
        last_capture = game.moves[ply - 1].end
        taken = previous.squares[last_capture]
        last_taken = taken.lower() if taken != EMPTY else "p"  # an empty square: en passant
    return MoveReview(ply, board.turn, move, game.sans[ply], kind, loss, before.best, best_san,
                      before.score, played_score, reply, reply_san, fen_before, fen_after,
                      last_capture, last_taken)  # fmt: skip


def build_reviews(game: Game, cache: AnalysisCache, levels=(ANALYSIS, REPLY)) -> list[MoveReview | None]:
    return [review_move(game, ply, cache, levels) for ply in range(len(game.moves))]


def review_game(game: Game, cache: AnalysisCache | None = None, levels=(ANALYSIS, REPLY)) -> list[MoveReview]:
    """Analyse every move of a game (in this thread) and grade it."""
    cache = cache or AnalysisCache()
    for fen, level in jobs_for(game, levels):
        cache.compute(fen, level)
    return [r for r in build_reviews(game, cache, levels) if r is not None]


@dataclass(frozen=True, slots=True)
class Summary:
    moves: int
    accuracy: float
    counts: Counter

    def line(self) -> str:
        """'Accuracy 82% · 2 mistakes · 1 blunder' (only the kinds that happened)."""
        parts = [f"Accuracy {self.accuracy:.0f}%"]
        for kind, word in (("blunder", "blunder"), ("mistake", "mistake"), ("miss", "missed chance"),
                           ("inaccuracy", "inaccuracy")):  # fmt: skip
            n = self.counts[kind]
            if n:
                plural = "inaccuracies" if kind == "inaccuracy" else word + "s"
                parts.append(f"{n} {word if n == 1 else plural}")
        return " · ".join(parts)


def summarise(reviews: list[MoveReview], color: str) -> Summary:
    mine = [r for r in reviews if r.color == color]
    accuracy = sum(r.accuracy for r in mine) / len(mine) if mine else 0.0
    return Summary(len(mine), accuracy, Counter(r.kind for r in mine))


def white_expected(fen: str, cache: AnalysisCache, level: Level = ANALYSIS) -> float | None:
    """How good the position is for White (0 to 1), for the evaluation bar and the graph."""
    found = cache.get(fen, level)
    if found is None:
        return None
    mover = expected(found.score)
    return mover if Board(fen).turn == WHITE else 1 - mover


class Analyst:
    """Analyses positions in a background thread, most urgent first, into an AnalysisCache.

    ``want(jobs)`` replaces the to-do list. ``paused`` is cleared while the computer opponent is
    thinking, so the two don't fight over the processor."""

    def __init__(self, threaded: bool = True, levels: tuple[Level, Level] = (ANALYSIS, REPLY)) -> None:
        self.cache = AnalysisCache()
        self.levels = levels
        self.threaded = threaded
        self.version = 0  # goes up each time a result lands, so the window knows to redraw
        self.allowed = threading.Event()
        self.allowed.set()
        self._jobs: list[tuple[str, Level]] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        if threaded:
            threading.Thread(target=self._run, daemon=True, name="chess-analyst").start()

    def want(self, jobs: list[tuple[str, Level]]) -> None:
        with self._lock:
            self._jobs = list(jobs)
        if self.threaded:
            self._wake.set()
        else:
            while (job := self._next()) is not None:
                self._do(job)

    def pending(self) -> int:
        with self._lock:
            jobs = list(self._jobs)
        return sum(self.cache.get(fen, level) is None for fen, level in jobs)

    def close(self) -> None:
        self._closed.set()
        self._wake.set()
        self.allowed.set()

    def _next(self) -> tuple[str, Level] | None:
        with self._lock:
            jobs = list(self._jobs)
        return next(((fen, level) for fen, level in jobs if self.cache.get(fen, level) is None), None)

    def _do(self, job: tuple[str, Level]) -> None:
        self.cache.compute(*job, stop=self._closed)
        self.version += 1

    def _run(self) -> None:
        while not self._closed.is_set():
            self.allowed.wait()
            self._wake.clear()
            job = self._next()
            if job is None:
                self._wake.wait(timeout=0.5)
                continue
            self._do(job)
