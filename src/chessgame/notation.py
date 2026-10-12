"""Chess notation: SAN for people ("Nf3", "exd5", "O-O", "e8=Q+") and PGN for saving games."""

import re
from datetime import date

from .board import BLACK, EMPTY, START_FEN, WHITE, Board, Move, square_name


def san(board: Board, move: Move, legal: list[Move] | None = None) -> str:
    """The move as people write it, e.g. 'Nbd7' or 'Qxf7#'. ``move`` must be legal on ``board``."""
    if legal is None:
        legal = board.legal_moves()
    piece = board.squares[move.start]
    kind = piece.lower()
    start_file, start_rank = square_name(move.start)

    if kind == "k" and abs(move.end - move.start) == 2:
        text = "O-O" if move.end > move.start else "O-O-O"
    elif kind == "p":
        capture = move.start % 8 != move.end % 8  # pawns only change file when they capture
        text = (start_file + "x" if capture else "") + square_name(move.end)
        if move.promotion:
            text += "=" + move.promotion.upper()
    else:
        # If another piece of the same kind can reach the same square, say which one moved:
        # by its file if that is enough, else by its rank, else both.
        rivals = [
            m.start
            for m in legal
            if m.end == move.end and m.start != move.start and board.squares[m.start] == piece
        ]
        hint = ""
        if rivals:
            if all(square_name(s)[0] != start_file for s in rivals):
                hint = start_file
            elif all(square_name(s)[1] != start_rank for s in rivals):
                hint = start_rank
            else:
                hint = start_file + start_rank
        capture = board.squares[move.end] != EMPTY
        text = kind.upper() + hint + ("x" if capture else "") + square_name(move.end)

    board.make(move)
    if board.in_check():
        text += "#" if not board.legal_moves() else "+"
    board.unmake()
    return text


def parse_move(board: Board, text: str) -> Move:
    """Read a move typed by a person: SAN ('Nf3', 'exd5', 'O-O', 'e8=Q') or UCI ('g1f3')."""
    legal = board.legal_moves()
    cleaned = text.strip().rstrip("+#!?").replace("0", "O")
    if cleaned.lower() in ("o-o", "o-o-o"):
        cleaned = cleaned.upper()
    if not cleaned:
        raise ValueError("type a move, like e4 or Nf3")

    uci = cleaned.lower()
    for move in legal:
        if move.uci() == uci or (move.promotion == "q" and move.uci()[:4] == uci):
            return move

    # Only moves that land on the square named in the text can match, so we write SAN for just
    # those few (writing SAN for every legal move would be slow when reading a whole opening book).
    wanted = cleaned.replace("=", "")
    targets = re.findall(r"[a-h][1-8]", cleaned)
    candidates = [m for m in legal if not targets or square_name(m.end) == targets[-1]]
    for move in candidates:
        if san(board, move, legal).rstrip("+#").replace("=", "") == wanted:
            return move
    # Be kind to lowercase piece letters ('nf3'), except 'b', which could be a pawn on the b-file.
    if cleaned[0] in "nrqk":
        return parse_move(board, cleaned[0].upper() + cleaned[1:])
    raise ValueError(f"{text.strip()!r} is not a legal move here")


def movetext(start_fen: str, sans: list[str]) -> str:
    """'1. e4 e5 2. Nf3 Nc6' (starting with '1...' if Black moved first)."""
    fields = start_fen.split()
    turn = fields[1]
    number = int(fields[5]) if len(fields) > 5 else 1
    parts = []
    for i, text in enumerate(sans):
        if turn == WHITE:
            parts.append(f"{number}. {text}")
            turn = BLACK
        else:
            parts.append(f"{number}... {text}" if i == 0 else text)
            turn, number = WHITE, number + 1
    return " ".join(parts)


def pgn(
    start_fen: str,
    sans: list[str],
    result: str = "*",
    white: str = "White",
    black: str = "Black",
    when: date | None = None,
) -> str:
    """A PGN file: the standard format every chess site and program can open."""
    when = when or date.today()
    headers = {
        "Event": "Casual game",
        "Site": "Chess in Python (Developers Assist)",
        "Date": when.strftime("%Y.%m.%d"),
        "Round": "-",
        "White": white,
        "Black": black,
        "Result": result,
    }
    if start_fen != START_FEN:
        headers |= {"SetUp": "1", "FEN": start_fen}
    head = "\n".join(f'[{key} "{value}"]' for key, value in headers.items())
    body = (movetext(start_fen, sans) + " " + result).strip()
    return f"{head}\n\n{_wrap(body)}\n"


def _wrap(text: str, width: int = 80) -> str:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return "\n".join([*lines, line])
