"""The coach's words: why a move is good, what went wrong, and what to play next.

Everything here turns numbers from ``analysis`` into short, plain sentences. The reasons are
simple rules (is it a capture? a check? does it develop a piece?), not deep understanding, so the
coach says nothing rather than something made up when no rule fits.
"""

from .analysis import Analysis, MoveReview, format_score, mate_in
from .board import EMPTY, WHITE, Board, Move, other, square_name
from .notation import san
from .openings import Opening, get_book

PIECES = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}
VALUES = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 0}
CENTRE = {"d4", "e4", "d5", "e5"}


def captured_piece(board: Board, move: Move) -> str | None:
    """The kind of piece a move captures ('p', 'n', ...), or None."""
    target = board.squares[move.end]
    if target != EMPTY:
        return target.lower()
    if board.squares[move.start].lower() == "p" and move.end == board.en_passant:
        return "p"
    return None


def reason(board: Board, move: Move, score: int | None = None) -> str:
    """Why a move is good, in a few words ('develops a knight'), or '' if no simple rule fits."""
    piece = board.squares[move.start].lower()
    mover = board.turn
    them = other(mover)
    taken = captured_piece(board, move)
    board.make(move)
    try:
        if board.in_check() and not board.legal_moves():
            return "is checkmate"
        gives_check = board.in_check()
        safe_after = not board.is_attacked(move.end, them)
    finally:
        board.unmake()
    mate = mate_in(score) if score is not None else None
    if mate and mate > 0:
        return f"starts a forced mate in {mate}"
    if move.promotion:
        return f"promotes a pawn to a {PIECES[move.promotion]}"
    if piece == "k" and abs(move.end - move.start) == 2:
        return "castles the king to safety and brings a rook into play"
    if taken:
        if safe_after:
            return f"wins the {PIECES[taken]} for free"
        if VALUES[taken] > VALUES[piece]:
            return f"wins material: a {PIECES[piece]} for a {PIECES[taken]}"
        return f"takes the {PIECES[taken]}"
    if gives_check:
        return "gives check"
    if board.is_attacked(move.start, them) and safe_after and piece != "p":
        return f"moves the {PIECES[piece]} out of danger"
    back_rank = 7 if mover == WHITE else 0
    if piece in "nb" and move.start // 8 == back_rank and board.fullmove <= 12:
        return f"develops a {PIECES[piece]}"
    if piece == "p" and square_name(move.end) in CENTRE:
        return "takes space in the centre"
    return ""


def suggestion(
    board: Board, analysis: Analysis | None, current: Opening | None = None
) -> tuple[Move, str] | None:
    """The coach's answer to "What should I play?": a move and why. Book moves come first, with
    the name and idea of the opening (``current`` is the opening the game is in so far)."""
    book = get_book()
    move = book.best(board)
    if move is not None:
        board.make(move)
        try:
            opening = book.openings.get(board.position_key())
        finally:
            board.unmake()
        text = f"Try {san(board, move)}: the main book move"
        if opening:
            text += f". It leads to the {opening.name}. {book.idea(opening)}"
        elif current:
            text += f" in the {current.name}. {book.idea(current)}"
        return move, text.rstrip(" .") + "."
    if analysis is None or analysis.best is None:
        return None
    why = reason(board, analysis.best, analysis.score)
    white_score = analysis.score if board.turn == WHITE else -analysis.score
    text = f"Try {san(board, analysis.best)}"
    text += f": it {why}." if why else "."
    text += f" Evaluation {format_score(white_score)}."
    return analysis.best, text


def explain(review: MoveReview) -> str:
    """One or two sentences about a graded move."""
    before = Board(review.fen_before)
    after = Board(review.fen_after)
    best_why = reason(before, review.best, review.best_score) if review.best else ""
    better = f"{review.best_san} was better" + (f": it {best_why}." if best_why else ".")
    match review.kind:
        case "book":
            opening = get_book().openings.get(after.position_key())
            named = f" ({opening.name})" if opening else ""
            return f"{review.san} is a book move{named}: a move masters play here."
        case "best":
            why = reason(before, review.move, review.played_score)
            return f"{review.san} is the best move" + (f": it {why}." if why else ".")
        case "excellent":
            return f"{review.san} is an excellent move, almost as good as {review.best_san}."
        case "good":
            return f"{review.san} is a good move. {review.best_san} was a little better."
        case "inaccuracy":
            return f"{review.san} is an inaccuracy. {better}"
        case "miss":
            return f"Missed chance! {_missed(before, review)}"
        case _:  # mistake or blunder
            return f"{review.san} is a {review.kind}. {_consequence(after, review)} {better}".replace(
                "  ", " "
            )


def _missed(before: Board, review: MoveReview) -> str:
    mate = mate_in(review.best_score)
    if mate and mate > 0:
        return f"{review.best_san} was mate in {mate}." if mate > 1 else f"{review.best_san} was checkmate."
    taken = captured_piece(before, review.best) if review.best else None
    if taken:
        return f"{review.best_san} would have won the {PIECES[taken]}."
    return f"{review.best_san} would have kept a winning position."


def _consequence(after: Board, review: MoveReview) -> str:
    """What the opponent can do after a bad move."""
    if review.reply is None:
        return ""
    mate = mate_in(review.played_score)
    if mate is not None and mate < 0:
        return f"It allows mate in {-mate}, starting with {review.reply_san}."
    taken = captured_piece(after, review.reply)
    if taken:
        return f"It allows {review.reply_san}, which takes a {PIECES[taken]}."
    if mate_in(review.best_score) is None:
        pawns = (review.best_score - review.played_score) / 100
        if pawns >= 1:
            amount = "1 pawn" if round(pawns) == 1 else f"{pawns:.0f} pawns"
            return f"It allows {review.reply_san} and costs about {amount} of value."
    return f"It allows {review.reply_san}."


def chance(review: MoveReview) -> str:
    """When the opponent's last move was bad: a nudge to find the punishment."""
    who = "White" if review.color == WHITE else "Black"
    return (
        f"{who}'s {review.san} was a {review.label.lower()}. There's a strong reply: can you find it? "
        "The lightbulb shows it."
    )


def side_name(color: str) -> str:
    return "White" if color == WHITE else "Black"
