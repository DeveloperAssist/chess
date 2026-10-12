"""Play in the terminal: no window needed. Type moves like e4, Nf3, O-O or e2e4."""

import sys
from collections.abc import Callable

from .ai import LEVELS, choose_move
from .analysis import BAD, analyse, review_game, summarise
from .board import BLACK, EMPTY, FILES, START_FEN, WHITE, Board
from .coach import explain, suggestion
from .game import Game
from .notation import san
from .openings import get_book

UNICODE = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟", strict=True))
HELP = """Type a move: e4, Nf3, exd5, O-O, e8=Q (or e2e4).
Other commands: hint, undo, moves, review, pgn, help, quit."""


def render(board: Board, white_at_bottom: bool = True, ascii_only: bool = False) -> str:
    """The board as text, with coordinates."""
    rows = range(8) if white_at_bottom else range(7, -1, -1)
    cols = list(range(8)) if white_at_bottom else list(range(7, -1, -1))
    files = "    " + " ".join(FILES[c] for c in cols)
    lines = [files]
    for r in rows:
        cells = []
        for c in cols:
            piece = board.squares[r * 8 + c]
            if ascii_only:
                cells.append(piece)  # "." for an empty square
            else:
                cells.append("·" if piece == EMPTY else UNICODE[piece])
        lines.append(f" {8 - r}  " + " ".join(cells) + f"  {8 - r}")
    lines.append(files)
    return "\n".join(lines)


def can_print_symbols(stream=None) -> bool:
    """Can this terminal show chess symbols? (Not when the output is piped on Windows, say.)"""
    encoding = getattr(stream or sys.stdout, "encoding", None) or "ascii"
    try:
        "♔♚·".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def review_text(game: Game, human: str | None = None) -> list[str]:
    """The end-of-game review as lines of text: a summary, then every mistake explained."""
    reviews = review_game(game)
    lines = []
    for color in (WHITE, BLACK):
        name = "White" if color == WHITE else "Black"
        if human:
            name = "You" if color == human else "Computer"
        lines.append(f"{name}: {summarise(reviews, color).line()}")
    for r in reviews:
        if r.kind in BAD and (human is None or r.color == human):
            number = f"{r.ply // 2 + 1}{'.' if r.color == WHITE else '...'}"
            lines.append(f"  {number} {r.san}: {explain(r)}")
    return lines


def play_in_terminal(
    opponent: str = "medium",
    human: str = WHITE,
    fen: str = START_FEN,
    ascii_only: bool = False,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    review: bool = True,
) -> Game:
    """The game loop. ``read`` and ``write`` can be swapped out, which is how the tests play."""
    game = Game(fen)
    vs_computer = opponent != "friend"
    level = LEVELS.get(opponent)
    book = get_book()
    opening = None
    write(
        f"Chess in Python. You play {'White' if human == WHITE else 'Black'}"
        + (f" against the computer ({level.name})." if level else " with a friend.")  # fmt: skip
        + " Type 'help' for commands."
    )
    show = True
    while (outcome := game.outcome()) is None:
        named = book.name(game.fens)
        if named and named != opening:
            opening = named
            write(f"Opening: {named.name}")
        if show:
            write("\n" + render(game.board, human == WHITE or not vs_computer, ascii_only))
            show = False
        side = "White" if game.turn == WHITE else "Black"
        if vs_computer and game.turn != human:
            result = choose_move(game.board, opponent, seen=game.positions())
            text = game.play(result.move)
            thought = "book move" if result.book else f"{result.seconds:.1f} s"
            write(f"Computer ({side}) plays {text}  ({thought})")
            show = True
            continue
        try:
            command = read(f"{side} to move{' (check!)' if game.board.in_check() else ''} > ").strip()
        except EOFError:
            command = "quit"
        match command.lower():
            case "" | "board":
                show = True
            case "quit" | "exit" | "q":
                write("Bye!")
                return game
            case "help" | "?":
                write(HELP)
            case "undo":
                game.undo()
                if vs_computer and game.moves and game.turn != human:
                    game.undo()
                show = True
            case "moves":
                legal = game.legal_moves()
                write(" ".join(sorted(san(game.board, m, legal) for m in legal)))
            case "hint":
                found = suggestion(game.board, analyse(game.board), book.name(game.fens))
                write(found[1] if found else "No moves to suggest.")
            case "review":
                write("\n".join(review_text(game, human if vs_computer else None)) or "No moves yet.")
            case "pgn":
                write(game.pgn())
            case _:
                try:
                    text = game.play(command)
                except ValueError as error:
                    write(f"{error}. Type 'moves' to see the legal moves.")
                    continue
                write(f"{side} plays {text}")
                show = not vs_computer
    write("\n" + render(game.board, human == WHITE or not vs_computer, ascii_only))
    write(outcome.describe())
    if review and game.moves:
        write("\nReviewing the game...")
        write("\n".join(review_text(game, human if vs_computer else None)))
    return game
