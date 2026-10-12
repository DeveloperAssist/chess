import pytest

from chessgame.analysis import analyse, review_game
from chessgame.board import Board, Move, square
from chessgame.coach import chance, explain, reason, suggestion
from chessgame.game import Game
from chessgame.notation import parse_move
from chessgame.openings import get_book


def why(fen: str, uci: str, score=None) -> str:
    return reason(Board(fen), Move.from_uci(uci), score)


@pytest.mark.parametrize(
    ("fen", "uci", "expected"),
    [
        ("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "h5f7", "is checkmate"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "castles the king to safety"),
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "g1f3", "develops a knight"),
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4", "takes space in the centre"),
        ("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", "d1d5", "wins the queen for free"),
        ("4k3/8/2p5/3r4/4P3/8/8/4K3 w - - 0 1", "e4d5", "wins material: a pawn for a rook"),
        ("4k3/8/8/8/8/8/1q6/R3K3 w - - 0 1", "a1a8", "gives check"),
    ],
)
def test_reasons(fen, uci, expected):
    assert why(fen, uci).startswith(expected)


def test_promotion_reason():
    assert why("8/4P3/8/8/8/8/k7/4K3 w - - 0 1", "e7e8q") == "promotes a pawn to a queen"


def test_taking_back_in_a_trade_is_a_recapture_not_a_free_piece():
    board = Board()
    for text in ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qe5", "Qe2", "Qxe2"]:
        board.make(parse_move(board, text))
    bxe2 = parse_move(board, "Bxe2")
    assert reason(board, bxe2) == "recaptures the queen"  # it knows from the board's history
    fresh = Board(board.fen())  # no history, so it has to be told where the last capture was
    assert reason(fresh, bxe2) == "wins the queen for free"
    assert reason(fresh, bxe2, last_capture=square("e2")) == "recaptures the queen"
    assert review_of("e4 d5 exd5 Qxd5 Nc3 Qe5 Qe2 Qxe2 Bxe2", 8).last_capture == square("e2")


def test_moving_out_of_danger():
    # The knight on c3 is attacked by a pawn; Ne2 takes it to safety.
    assert why("4k3/8/8/8/1p6/2N5/8/4K3 w - - 0 1", "c3e2") == "moves the knight out of danger"


def test_mate_score_reason():
    assert why("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1b1", 100_000 - 3) == "starts a forced mate in 2"


def test_no_reason_when_no_rule_fits():
    assert why("4k3/8/8/8/8/8/P7/4K3 w - - 0 1", "a2a3") == ""


def test_suggestion_prefers_the_book():
    game = Game()
    for move in ["e4", "e5", "Nf3", "Nc6"]:
        game.play(move)
    move, text = suggestion(game.board, None, get_book().name(game.fens))
    assert move == Move.from_uci("f1c4")
    assert "Italian Game" in text and "f7" in text


def test_suggestion_out_of_book_uses_the_analysis():
    board = Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    move, text = suggestion(board, analyse(board))
    assert move == Move.from_uci("a1a8")
    assert text == "Try Ra8#: it is checkmate. Evaluation M1."
    assert suggestion(board, None) is None  # no book move and no analysis yet


def review_of(moves: str, ply: int, fen: str | None = None):
    game = Game(fen) if fen else Game()
    for move in moves.split():
        game.play(move)
    return review_game(game)[ply]


def test_explaining_a_blunder_that_allows_mate():
    text = explain(review_of("e4 e5 Qh5 Nc6 Bc4 Nf6", 5))
    assert text.startswith("Nf6 is a blunder. It allows mate in 1, starting with Qxf7#.")


def test_explaining_a_blunder_that_loses_the_queen():
    text = explain(review_of("e4 e5 Nf3 Qh4", 3))
    assert "It allows Nxh4, which takes a queen." in text


def test_explaining_book_best_and_missed_moves():
    assert "book move (King's Pawn Opening)" in explain(review_of("e4", 0))
    assert explain(review_of("e4 e5 Nf3 Qh4 Nxh4", 4)) == "Nxh4 is the best move: it wins the queen for free."
    missed = explain(review_of("h3", 0, fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"))
    assert missed == "Missed chance! Ra8# was checkmate."


def test_chance_nudges_you_to_punish_a_blunder():
    text = chance(review_of("e4 e5 Nf3 Qh4", 3))
    assert text.startswith("Black's Qh4 was a blunder.") and "lightbulb" in text
