import dataclasses
import threading
import time

import pytest

from chessgame.ai import LEVELS, MATE, Level, choose_move, evaluate
from chessgame.board import Board, Move
from chessgame.game import Game


@pytest.mark.parametrize("level", ["medium", "hard"])
def test_finds_mate_in_one(level):
    board = Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    result = choose_move(board, level, seed=1)
    assert result.move == Move.from_uci("h5f7")  # Scholar's mate
    assert result.score >= MATE - 10


def test_finds_a_back_rank_mate_in_two():
    game = Game("r5k1/5ppp/8/8/8/8/3R4/3R2K1 w - - 0 1")  # 1. Rd8+ Rxd8 2. Rxd8#
    game.play(choose_move(game.board, "hard", seed=1).move)
    game.play(choose_move(game.board, "hard", seed=1).move)
    game.play(choose_move(game.board, "hard", seed=1).move)
    assert game.outcome() is not None and game.outcome().reason == "checkmate"


@pytest.mark.parametrize("level", ["easy", "medium", "hard"])
def test_takes_a_free_queen(level):
    board = Board("rnb1kbnr/pppp1ppp/8/4p3/3qP3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 4")
    assert choose_move(board, level, seed=3).move == Move.from_uci("f3d4")


def test_medium_does_not_grab_a_defended_pawn_with_its_queen():
    # Qxd5?? would lose the queen to ...Nxd5 (not seen without looking at the reply).
    board = Board("rnbqkb1r/ppp1pppp/5n2/3p4/8/5Q2/PPPPPPPP/RNB1KBNR w KQkq - 0 3")
    assert choose_move(board, "medium", seed=1).move != Move.from_uci("f3d5")


def test_no_legal_moves_means_no_move():
    stalemate = Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert choose_move(stalemate, "hard") is None


@pytest.mark.parametrize("level", list(LEVELS))
def test_every_level_plays_legal_moves_and_leaves_the_board_alone(level):
    board = Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    before = board.fen()
    quick = dataclasses.replace(LEVELS[level], seconds=1.0)
    result = choose_move(board, quick, seed=2)
    assert result.move in board.legal_moves()
    assert board.fen() == before  # it searched on its own copy


def test_stop_event_ends_the_search_quickly():
    stop = threading.Event()
    stop.set()
    started = time.perf_counter()
    slow = Level("Slow", depth=8, seconds=60, noise=0, quiescence=True)
    result = choose_move(Board(), slow, stop=stop, book=False)
    assert time.perf_counter() - started < 2
    assert result.move in Board().legal_moves()


def test_avoids_a_repetition_draw_when_winning():
    # White is a queen up. Shuffling back to a position seen twice would be a draw by repetition.
    game = Game("6k1/8/8/8/8/8/5Q2/6K1 w - - 0 1")
    for move in ["Qf3", "Kg7", "Qf2", "Kg8", "Qf3", "Kg7", "Qf2", "Kg8"]:
        game.play(move)
    result = choose_move(game.board, "hard", seen=game.positions(), seed=1)
    game.play(result.move)
    assert game.outcome() is None


@pytest.mark.parametrize("fen", ["8/8/8/4k3/8/8/8/3QK3 w - - 0 1", "8/8/3k4/8/8/8/8/R3K3 w - - 0 1"])
def test_hard_mates_a_lone_king(fen):
    """Needs the mop-up evaluation: without it the computer wanders until the game is drawn."""
    game = Game(fen)
    while game.outcome() is None and len(game.moves) < 120:
        game.play(choose_move(game.board, "hard", seen=game.positions(), seed=1).move)
    assert game.outcome().reason == "checkmate"


def test_evaluation_is_symmetric():
    """The same position with colours swapped (and the board flipped) scores the same."""
    fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 5"
    mirrored = "rnbqk2r/ppp2ppp/3p1n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R b KQkq - 0 5"
    assert evaluate(Board(fen)) == evaluate(Board(mirrored))


def test_evaluation_counts_material_for_the_side_to_move():
    up_a_queen = Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    assert evaluate(up_a_queen) > 800
    up_a_queen.turn = "b"
    assert evaluate(up_a_queen) < -800
