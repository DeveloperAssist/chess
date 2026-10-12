"""Perft counts from https://www.chessprogramming.org/Perft_Results. If every count matches, the
move generator follows the rules (castling, en passant, promotions, pins, checks)."""

import pytest

from chessgame.board import START_FEN, Board
from chessgame.perft import divide, perft

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POSITION_3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POSITION_4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
POSITION_5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
POSITION_6 = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"


@pytest.mark.parametrize(
    ("fen", "depth", "count"),
    [
        (START_FEN, 1, 20),
        (START_FEN, 2, 400),
        (START_FEN, 3, 8_902),
        (KIWIPETE, 1, 48),
        (KIWIPETE, 2, 2_039),
        (POSITION_3, 1, 14),
        (POSITION_3, 2, 191),
        (POSITION_3, 3, 2_812),
        (POSITION_4, 1, 6),
        (POSITION_4, 2, 264),
        (POSITION_4, 3, 9_467),
        (POSITION_5, 1, 44),
        (POSITION_5, 2, 1_486),
        (POSITION_6, 1, 46),
        (POSITION_6, 2, 2_079),
    ],
)
def test_perft(fen, depth, count):
    assert perft(Board(fen), depth) == count


@pytest.mark.slow
@pytest.mark.parametrize(
    ("fen", "depth", "count"),
    [
        (START_FEN, 4, 197_281),
        (KIWIPETE, 3, 97_862),
        (POSITION_3, 4, 43_238),
        (POSITION_5, 3, 62_379),
        (POSITION_6, 3, 89_890),
    ],
)
def test_perft_deeper(fen, depth, count):
    assert perft(Board(fen), depth) == count


def test_perft_leaves_the_board_unchanged():
    board = Board(KIWIPETE)
    perft(board, 3)
    assert board.fen() == KIWIPETE
    assert board.history == []


def test_divide_adds_up_to_perft():
    counts = divide(Board(START_FEN), 3)
    assert len(counts) == 20
    assert counts["e2e4"] == 600
    assert sum(counts.values()) == 8_902
