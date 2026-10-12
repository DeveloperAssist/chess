import pytest

from chessgame.board import BLACK, WHITE
from chessgame.game import Game


def play(game: Game, moves: str) -> Game:
    for move in moves.split():
        game.play(move)
    return game


def test_fools_mate():
    game = play(Game(), "f3 e5 g4 Qh4")
    assert game.sans[-1] == "Qh4#"
    outcome = game.outcome()
    assert (outcome.result, outcome.reason, outcome.winner) == ("0-1", "checkmate", BLACK)
    assert outcome.describe() == "Checkmate. Black wins."


def test_stalemate():
    game = play(Game("7k/8/5Q2/6K1/8/8/8/8 w - - 0 1"), "Qf7")
    assert game.outcome().reason == "stalemate"
    assert game.outcome().result == "1/2-1/2"


def test_threefold_repetition():
    game = Game()
    play(game, "Nf3 Nf6 Ng1 Ng8 Nf3 Nf6 Ng1")
    assert game.outcome() is None
    game.play("Ng8")  # the start position, for the third time
    assert game.outcome().reason == "threefold repetition"
    game.undo()
    assert game.outcome() is None


def test_fifty_move_rule():
    game = Game("4k3/8/8/8/8/8/R7/4K3 w - - 99 80")
    game.play("Ra3")
    assert game.outcome().reason == "50-move rule"


def test_insufficient_material_after_a_capture():
    game = play(Game("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1"), "Kxe2")
    assert game.outcome().reason == "insufficient material"


def test_illegal_moves_are_refused_and_change_nothing():
    game = Game()
    with pytest.raises(ValueError):
        game.play("e5")
    assert game.moves == [] and game.turn == WHITE


def test_undo_takes_back_moves_in_order():
    game = play(Game(), "e4 e5 Nf3")
    assert game.undo().uci() == "g1f3"
    assert game.sans == ["e4", "e5"]
    assert game.turn == WHITE
    game.undo()
    game.undo()
    assert game.undo() is None
    assert game.board.fen() == game.start_fen
    assert game.seen[game.board.position_key()] == 1


def test_captured_pieces_and_material():
    game = play(Game(), "e4 e5 Qh5 Nc6 Qxf7+ Kxf7")  # a pawn for the queen: a bad trade
    assert game.captured(BLACK) == ["p"]
    assert game.captured(WHITE) == ["Q"]
    assert game.material() == 1 - 9


def test_captured_pieces_from_a_custom_start():
    game = play(Game("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"), "exd5")
    assert game.captured(BLACK) == ["p"] and game.captured(WHITE) == []
    game.undo()
    assert game.captured(BLACK) == []


def test_positions_remembers_what_was_played_and_forgets_undone_moves():
    game = play(Game(), "Nf3 Nf6")
    keys = game.positions()
    assert len(keys) == 3 and game.board.position_key() in keys
    game.undo()
    assert len(game.positions()) == 2


def test_pgn_of_a_finished_game():
    game = play(Game(), "f3 e5 g4 Qh4")
    text = game.pgn("You", "Computer")
    assert text.strip().endswith("1. f3 e5 2. g4 Qh4# 0-1")
