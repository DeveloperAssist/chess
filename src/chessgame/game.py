"""A game of chess: the board plus everything a real game remembers (the moves played, how often
each position has appeared) and how it ends."""

from collections import Counter
from dataclasses import dataclass

from .board import EMPTY, START_FEN, WHITE, Board, Move, color_of, other
from .notation import parse_move, pgn, san

VALUES = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 0}


@dataclass(frozen=True, slots=True)
class Outcome:
    result: str  # "1-0", "0-1" or "1/2-1/2", as written in PGN files
    reason: str  # "checkmate", "stalemate", "threefold repetition", "50-move rule", ...
    winner: str | None  # WHITE, BLACK or None for a draw

    def describe(self) -> str:
        if self.winner:
            return f"{self.reason.capitalize()}. {'White' if self.winner == WHITE else 'Black'} wins."
        return f"Draw by {self.reason}."


class Game:
    """Play moves, take them back, and ask whether the game is over."""

    def __init__(self, fen: str = START_FEN) -> None:
        self.board = Board(fen)
        self.start_fen = self.board.fen()
        self.moves: list[Move] = []
        self.sans: list[str] = []
        self.fens = [self.start_fen]  # fens[i] is the position before move i; the last is now
        self.seen = Counter([self.board.position_key()])  # position -> times it has appeared
        self._legal: list[Move] | None = None

    @property
    def turn(self) -> str:
        return self.board.turn

    def legal_moves(self) -> list[Move]:
        if self._legal is None:  # worked out once per position, then reused
            self._legal = self.board.legal_moves()
        return self._legal

    def play(self, move: Move | str) -> str:
        """Play a move (a Move, or text like 'e4', 'Nf3', 'e2e4') and return it in SAN."""
        if isinstance(move, str):
            move = parse_move(self.board, move)
        legal = self.legal_moves()
        if move not in legal:
            raise ValueError(f"{move} is not a legal move here")
        text = san(self.board, move, legal)
        self.board.make(move)
        self.moves.append(move)
        self.sans.append(text)
        self.fens.append(self.board.fen())
        self.seen[self.board.position_key()] += 1
        self._legal = None
        return text

    def undo(self) -> Move | None:
        """Take back the last move (None if there is nothing to take back)."""
        if not self.moves:
            return None
        self.seen[self.board.position_key()] -= 1
        self.board.unmake()
        self.sans.pop()
        self.fens.pop()
        self._legal = None
        return self.moves.pop()

    @property
    def last_move(self) -> Move | None:
        return self.moves[-1] if self.moves else None

    def outcome(self) -> Outcome | None:
        """How the game ended, or None if it is still going."""
        board = self.board
        if not self.legal_moves():
            if board.in_check():
                winner = other(board.turn)  # the side to move has been mated
                return Outcome("1-0" if winner == WHITE else "0-1", "checkmate", winner)
            return Outcome("1/2-1/2", "stalemate", None)
        if board.insufficient_material():
            return Outcome("1/2-1/2", "insufficient material", None)
        if self.seen[board.position_key()] >= 3:
            return Outcome("1/2-1/2", "threefold repetition", None)
        if board.halfmove >= 100:
            return Outcome("1/2-1/2", "50-move rule", None)
        return None

    def positions(self) -> set[str]:
        """Every position played so far. The computer player uses it to avoid (or aim for) a
        draw by repetition."""
        return {key for key, count in self.seen.items() if count > 0}

    def captured(self, color: str) -> list[str]:
        """The pieces of ``color`` taken in this game, most valuable first. The board's undo
        stack already remembers every captured piece, so we just read it."""
        taken = [u.captured for u in self.board.history if u.captured != EMPTY]
        return sorted((p for p in taken if color_of(p) == color), key=lambda p: -VALUES[p.lower()])

    def material(self) -> int:
        """White's material minus Black's, in pawns (queen = 9, rook = 5, ...)."""
        score = 0
        for p in self.board.squares:
            if p != ".":
                score += VALUES[p.lower()] if p.isupper() else -VALUES[p.lower()]
        return score

    def pgn(self, white: str = "White", black: str = "Black") -> str:
        outcome = self.outcome()
        return pgn(self.start_fen, self.sans, outcome.result if outcome else "*", white, black)
