"""The rules of chess: the board, the moves, check, and taking moves back.

No chess library does the work here. It is plain Python you can read from top to bottom.

How the board is stored
-----------------------
The board is a list of 64 one-letter strings, one per square. Square 0 is a8 (top-left when
White sits at the bottom) and square 63 is h1, so ``row, col = divmod(square, 8)``::

         a   b   c   d   e   f   g   h
    8    0   1   2   3   4   5   6   7
    7    8   9  10  11  12  13  14  15
    ...
    2   48  49  50  51  52  53  54  55
    1   56  57  58  59  60  61  62  63

Each square holds a piece letter, the same letters FEN uses: uppercase is White (K Q R B N P),
lowercase is Black (k q r b n p), and "." is an empty square.
"""

from dataclasses import dataclass
from typing import NamedTuple

WHITE, BLACK = "w", "b"
EMPTY = "."
FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PROMOTIONS = "qrbn"


def other(color: str) -> str:
    """The opponent's colour."""
    return BLACK if color == WHITE else WHITE


def color_of(piece: str) -> str:
    """'K' -> 'w', 'k' -> 'b'."""
    return WHITE if piece.isupper() else BLACK


def square(name: str) -> int:
    """'e4' -> 36."""
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError(f"{name!r} is not a square (try something like 'e4')")
    return (8 - int(name[1])) * 8 + FILES.index(name[0])


def square_name(sq: int) -> str:
    """36 -> 'e4'."""
    row, col = divmod(sq, 8)
    return f"{FILES[col]}{8 - row}"


# --- Lookup tables, worked out once when the module loads ------------------------------------
# Asking "where can a knight on g1 jump?" happens millions of times in a search, so we answer
# every such question once, up front, and keep the answers in lists.

STRAIGHT = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
KNIGHT = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))


def _ray(sq: int, dr: int, dc: int) -> tuple[int, ...]:
    """The squares in one direction from sq, nearest first, up to the edge of the board."""
    row, col = divmod(sq, 8)
    squares = []
    row, col = row + dr, col + dc
    while 0 <= row < 8 and 0 <= col < 8:
        squares.append(row * 8 + col)
        row, col = row + dr, col + dc
    return tuple(squares)


def _steps(sq: int, offsets: tuple[tuple[int, int], ...]) -> tuple[int, ...]:
    """The squares one step away from sq in each direction that stays on the board."""
    row, col = divmod(sq, 8)
    return tuple((row + dr) * 8 + col + dc for dr, dc in offsets if 0 <= row + dr < 8 and 0 <= col + dc < 8)


ROOK_RAYS = [tuple(r for d in STRAIGHT if (r := _ray(sq, *d))) for sq in range(64)]
BISHOP_RAYS = [tuple(r for d in DIAGONAL if (r := _ray(sq, *d))) for sq in range(64)]
QUEEN_RAYS = [ROOK_RAYS[sq] + BISHOP_RAYS[sq] for sq in range(64)]
KNIGHT_JUMPS = [_steps(sq, KNIGHT) for sq in range(64)]
KING_STEPS = [_steps(sq, STRAIGHT + DIAGONAL) for sq in range(64)]
# PAWN_ATTACKS[colour][sq]: the two squares a pawn of that colour standing on sq attacks.
# White pawns attack up the board (towards row 0), Black pawns down.
PAWN_ATTACKS = {
    WHITE: [_steps(sq, ((-1, -1), (-1, 1))) for sq in range(64)],
    BLACK: [_steps(sq, ((1, -1), (1, 1))) for sq in range(64)],
}


class Castle(NamedTuple):
    right: str  # the FEN letter: K, Q (White) or k, q (Black)
    king_from: int
    king_to: int
    rook_from: int
    rook_to: int
    must_be_empty: tuple[int, ...]
    king_path: tuple[int, ...]  # the king may not be in check on any of these squares


CASTLES = (
    Castle("K", square("e1"), square("g1"), square("h1"), square("f1"),
           (square("f1"), square("g1")), (square("e1"), square("f1"), square("g1"))),
    Castle("Q", square("e1"), square("c1"), square("a1"), square("d1"),
           (square("b1"), square("c1"), square("d1")), (square("e1"), square("d1"), square("c1"))),
    Castle("k", square("e8"), square("g8"), square("h8"), square("f8"),
           (square("f8"), square("g8")), (square("e8"), square("f8"), square("g8"))),
    Castle("q", square("e8"), square("c8"), square("a8"), square("d8"),
           (square("b8"), square("c8"), square("d8")), (square("e8"), square("d8"), square("c8"))),
)  # fmt: skip

# When anything moves from or to one of these squares, those castling rights are gone for good:
# the king or the rook has moved, or the rook was captured.
RIGHTS_LOST = {square("e1"): "KQ", square("e8"): "kq"} | {c.rook_from: c.right for c in CASTLES}


# --- Moves ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Move:
    """A move from one square to another. ``promotion`` is 'q', 'r', 'b' or 'n' when a pawn
    reaches the last rank. Castling is just the king moving two squares."""

    start: int
    end: int
    promotion: str = ""

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        """'e2e4' or 'e7e8q' (the format chess engines use) -> Move."""
        text = text.strip().lower()
        if len(text) not in (4, 5) or (len(text) == 5 and text[4] not in PROMOTIONS):
            raise ValueError(f"{text!r} is not a move like 'e2e4' or 'e7e8q'")
        return cls(square(text[:2]), square(text[2:4]), text[4:])

    def uci(self) -> str:
        return square_name(self.start) + square_name(self.end) + self.promotion

    def __str__(self) -> str:
        return self.uci()


@dataclass(slots=True)
class Undo:
    """Everything ``unmake`` needs to put the board back exactly as it was."""

    move: Move
    piece: str  # the piece that moved (still a pawn, even if it promoted)
    captured: str  # EMPTY if nothing was captured
    captured_at: int  # not the same as move.end for en passant
    castling: str
    en_passant: int | None
    halfmove: int


# --- The board --------------------------------------------------------------------------------


class Board:
    """A chess position you can make moves on and take them back.

    ``make`` pushes an ``Undo`` record on ``history`` and ``unmake`` pops it: a stack.
    """

    def __init__(self, fen: str = START_FEN) -> None:
        self.squares: list[str] = [EMPTY] * 64
        self.turn = WHITE
        self.castling = ""  # some of "KQkq", or "" when nobody can castle
        self.en_passant: int | None = None  # the square a pawn just skipped over, if any
        self.halfmove = 0  # moves since the last capture or pawn move (for the 50-move rule)
        self.fullmove = 1
        self.kings = {WHITE: -1, BLACK: -1}  # where each king stands, so check tests are quick
        self.history: list[Undo] = []
        self.set_fen(fen)

    # -- FEN: one line of text that describes a whole position --

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError("a FEN needs at least 4 parts: pieces, turn, castling, en passant")
        placement, turn, castling, en_passant = parts[:4]
        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError("a FEN board needs 8 rows separated by '/'")
        squares: list[str] = []
        for row in rows:
            cells: list[str] = []
            for ch in row:
                if ch in "12345678":
                    cells.extend(EMPTY * int(ch))
                elif ch in "KQRBNPkqrbnp":
                    cells.append(ch)
                else:
                    raise ValueError(f"unexpected {ch!r} in the FEN board")
            if len(cells) != 8:
                raise ValueError(f"the FEN row {row!r} does not have 8 squares")
            squares += cells
        if squares.count("K") != 1 or squares.count("k") != 1:
            raise ValueError("each side needs exactly one king")
        if turn not in (WHITE, BLACK):
            raise ValueError("the turn must be 'w' or 'b'")
        if castling != "-" and not set(castling) <= set("KQkq"):
            raise ValueError("castling must be '-' or letters from 'KQkq'")

        self.squares = squares
        self.turn = turn
        # Keep a castling right only if the king and rook really are on their starting squares.
        king = {"K": "K", "Q": "K", "k": "k", "q": "k"}
        self.castling = "".join(
            c.right
            for c in CASTLES
            if c.right in castling
            and squares[c.king_from] == king[c.right]
            and squares[c.rook_from] == ("R" if c.right.isupper() else "r")
        )
        self.en_passant = None if en_passant == "-" else square(en_passant)
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self.kings = {WHITE: squares.index("K"), BLACK: squares.index("k")}
        self.history = []

    def placement(self) -> str:
        """The piece part of the FEN, e.g. 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR'."""
        rows = []
        for r in range(8):
            text, gap = "", 0
            for piece in self.squares[r * 8 : r * 8 + 8]:
                if piece == EMPTY:
                    gap += 1
                    continue
                if gap:
                    text, gap = text + str(gap), 0
                text += piece
            rows.append(text + (str(gap) if gap else ""))
        return "/".join(rows)

    def fen(self) -> str:
        ep = "-" if self.en_passant is None else square_name(self.en_passant)
        return f"{self.placement()} {self.turn} {self.castling or '-'} {ep} {self.halfmove} {self.fullmove}"

    def position_key(self) -> str:
        """What makes two positions 'the same' for threefold repetition: the pieces, whose turn it
        is, castling rights, and an en passant capture only if one is actually possible."""
        ep = "-"
        if self.en_passant is not None:
            pawn = "P" if self.turn == WHITE else "p"
            # Our pawns that could take on the en passant square stand where an enemy pawn on
            # that square would attack.
            if any(self.squares[s] == pawn for s in PAWN_ATTACKS[other(self.turn)][self.en_passant]):
                ep = square_name(self.en_passant)
        return f"{self.placement()} {self.turn} {self.castling or '-'} {ep}"

    def copy(self) -> "Board":
        """A separate board in the same position (without the move history)."""
        return Board(self.fen())

    def __str__(self) -> str:
        rows = [" ".join(self.squares[r * 8 : r * 8 + 8]) for r in range(8)]
        return "\n".join(rows)

    # -- Making and taking back moves --

    def make(self, move: Move) -> None:
        """Play a move. It must come from ``legal_moves`` (or ``pseudo_moves``)."""
        sq = self.squares
        piece = sq[move.start]
        mover = self.turn
        kind = piece.lower()

        captured_at = move.end
        if kind == "p" and move.end == self.en_passant:
            # En passant: the captured pawn is not on the square we move to, but beside it.
            captured_at = move.end + (8 if mover == WHITE else -8)
        captured = sq[captured_at]
        self.history.append(
            Undo(move, piece, captured, captured_at, self.castling, self.en_passant, self.halfmove)
        )

        sq[captured_at] = EMPTY
        sq[move.start] = EMPTY
        if move.promotion:
            piece = move.promotion.upper() if mover == WHITE else move.promotion
        sq[move.end] = piece

        if kind == "k":
            self.kings[mover] = move.end
            if abs(move.end - move.start) == 2:  # castling: the rook jumps over the king
                rook_from, rook_to = _castle_rook(move)
                sq[rook_to], sq[rook_from] = sq[rook_from], EMPTY

        if self.castling:
            for s in (move.start, move.end):
                if s in RIGHTS_LOST:
                    self.castling = "".join(c for c in self.castling if c not in RIGHTS_LOST[s])

        double_step = kind == "p" and abs(move.end - move.start) == 16
        self.en_passant = (move.start + move.end) // 2 if double_step else None
        self.halfmove = 0 if kind == "p" or captured != EMPTY else self.halfmove + 1
        if mover == BLACK:
            self.fullmove += 1
        self.turn = other(mover)

    def unmake(self) -> Move:
        """Take back the last move and return it."""
        undo = self.history.pop()
        move = undo.move
        sq = self.squares
        mover = other(self.turn)

        sq[move.end] = EMPTY
        sq[move.start] = undo.piece
        sq[undo.captured_at] = undo.captured
        if undo.piece in "Kk":
            self.kings[mover] = move.start
            if abs(move.end - move.start) == 2:
                rook_from, rook_to = _castle_rook(move)
                sq[rook_from], sq[rook_to] = sq[rook_to], EMPTY

        self.castling, self.en_passant, self.halfmove = undo.castling, undo.en_passant, undo.halfmove
        if mover == BLACK:
            self.fullmove -= 1
        self.turn = mover
        return move

    # -- Attacks and check --

    def is_attacked(self, target: int, by: str) -> bool:
        """Can any piece of colour ``by`` capture on ``target``? We look outwards from the target
        square, as if it were each kind of piece, and see if we hit an attacker of that kind."""
        sq = self.squares
        pawn, knight, bishop, rook, queen, king = "PNBRQK" if by == WHITE else "pnbrqk"
        # A pawn attacks target if it stands where a pawn of the OTHER colour on target would attack.
        for s in PAWN_ATTACKS[other(by)][target]:
            if sq[s] == pawn:
                return True
        for s in KNIGHT_JUMPS[target]:
            if sq[s] == knight:
                return True
        for s in KING_STEPS[target]:
            if sq[s] == king:
                return True
        for ray in ROOK_RAYS[target]:
            for s in ray:
                if sq[s] != EMPTY:
                    if sq[s] == rook or sq[s] == queen:
                        return True
                    break
        for ray in BISHOP_RAYS[target]:
            for s in ray:
                if sq[s] != EMPTY:
                    if sq[s] == bishop or sq[s] == queen:
                        return True
                    break
        return False

    def in_check(self, color: str | None = None) -> bool:
        """Is this colour's king attacked? (The side to move, if no colour is given.)"""
        color = color or self.turn
        return self.is_attacked(self.kings[color], other(color))

    # -- Move generation --

    def pseudo_moves(self) -> list[Move]:
        """Every move that follows the way the pieces move, before we check whether it leaves our
        own king in check."""
        moves: list[Move] = []
        white = self.turn == WHITE
        for s, piece in enumerate(self.squares):
            if piece == EMPTY or piece.isupper() != white:
                continue
            match piece.lower():
                case "p":
                    self._pawn_moves(s, white, moves)
                case "n":
                    self._step_moves(s, KNIGHT_JUMPS[s], white, moves)
                case "b":
                    self._slide_moves(s, BISHOP_RAYS[s], white, moves)
                case "r":
                    self._slide_moves(s, ROOK_RAYS[s], white, moves)
                case "q":
                    self._slide_moves(s, QUEEN_RAYS[s], white, moves)
                case "k":
                    self._step_moves(s, KING_STEPS[s], white, moves)
                    self._castle_moves(white, moves)
        return moves

    def legal_moves(self) -> list[Move]:
        """The moves you are allowed to play: try each one, and keep it only if our king is not
        in check afterwards."""
        mover, them = self.turn, other(self.turn)
        legal = []
        for move in self.pseudo_moves():
            self.make(move)
            if not self.is_attacked(self.kings[mover], them):
                legal.append(move)
            self.unmake()
        return legal

    def _step_moves(self, s: int, targets: tuple[int, ...], white: bool, moves: list[Move]) -> None:
        for t in targets:
            piece = self.squares[t]
            if piece == EMPTY or piece.isupper() != white:
                moves.append(Move(s, t))

    def _slide_moves(self, s: int, rays: tuple[tuple[int, ...], ...], white: bool, moves: list[Move]) -> None:
        for ray in rays:
            for t in ray:
                piece = self.squares[t]
                if piece == EMPTY:
                    moves.append(Move(s, t))
                    continue
                if piece.isupper() != white:
                    moves.append(Move(s, t))  # capture, then the ray is blocked
                break

    def _pawn_moves(self, s: int, white: bool, moves: list[Move]) -> None:
        sq = self.squares
        forward, start_row, last_row = (-8, 6, 0) if white else (8, 1, 7)
        one = s + forward

        def add(end: int) -> None:
            if end // 8 == last_row:
                moves.extend(Move(s, end, p) for p in PROMOTIONS)
            else:
                moves.append(Move(s, end))

        if sq[one] == EMPTY:
            add(one)
            if s // 8 == start_row and sq[one + forward] == EMPTY:
                moves.append(Move(s, one + forward))
        for t in PAWN_ATTACKS[WHITE if white else BLACK][s]:
            if sq[t] != EMPTY and sq[t].isupper() != white:
                add(t)
            elif t == self.en_passant:
                moves.append(Move(s, t))

    def _castle_moves(self, white: bool, moves: list[Move]) -> None:
        if not self.castling:
            return
        them = BLACK if white else WHITE
        for c in CASTLES:
            if (
                c.right in self.castling
                and c.right.isupper() == white
                and all(self.squares[s] == EMPTY for s in c.must_be_empty)
                and not any(self.is_attacked(s, them) for s in c.king_path)
            ):
                moves.append(Move(c.king_from, c.king_to))

    # -- How the game can end --

    def is_checkmate(self) -> bool:
        return self.in_check() and not self.legal_moves()

    def is_stalemate(self) -> bool:
        return not self.in_check() and not self.legal_moves()

    def insufficient_material(self) -> bool:
        """True when nobody can ever checkmate: king against king, king and one bishop or knight
        against a king, or kings with bishops that all stand on the same colour of square."""
        others = [(s, p) for s, p in enumerate(self.squares) if p not in (EMPTY, "K", "k")]
        if any(p.lower() in "pqr" for _, p in others):
            return False
        if len(others) <= 1:
            return True
        if all(p.lower() == "b" for _, p in others):
            shades = {(s // 8 + s % 8) % 2 for s, _ in others}
            return len(shades) == 1
        return False


def _castle_rook(move: Move) -> tuple[int, int]:
    """For a castling king move, where the rook goes from and to."""
    if move.end > move.start:  # king side: the rook on the h-file jumps to the f-file
        return move.start + 3, move.start + 1
    return move.start - 4, move.start - 1  # queen side: a-file to d-file
