from datetime import date

import pytest

from chessgame.board import Board, Move
from chessgame.notation import movetext, parse_move, pgn, san


def san_of(fen: str, uci: str) -> str:
    return san(Board(fen), Move.from_uci(uci))


@pytest.mark.parametrize(
    ("fen", "uci", "expected"),
    [
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4", "e4"),
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "g1f3", "Nf3"),
        ("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2", "e4d5", "exd5"),
        ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", "exd6"),  # en passant
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "O-O"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1c1", "O-O-O"),
        ("3k4/4P3/8/8/8/8/8/4K3 w - - 0 1", "e7e8q", "e8=Q+"),
        ("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "a1a8", "Ra8#"),
        ("4k3/8/8/8/8/8/8/1N1NK3 w - - 0 1", "b1c3", "Nbc3"),  # same rank: say the file
        ("4k3/8/8/8/8/1N6/8/1N2K3 w - - 0 1", "b1d2", "N1d2"),  # same file: say the rank
        ("8/7k/8/8/Q1Q5/8/8/Q3K3 w - - 0 1", "a4b3", "Qab3"),  # the a1 queen can't reach b3
        ("7k/8/8/8/Q1Q5/8/Q7/4K3 w - - 0 1", "a4b3", "Qa4b3"),  # both are needed
    ],
)
def test_san(fen, uci, expected):
    assert san_of(fen, uci) == expected


@pytest.mark.parametrize("text", ["Nf3", "nf3", "g1f3", "Nf3+", " Nf3 "])
def test_parse_move_accepts_san_and_uci(text):
    assert parse_move(Board(), text) == Move.from_uci("g1f3")


def test_parse_castling_with_zeros_or_lowercase():
    board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert parse_move(board, "0-0") == Move.from_uci("e1g1")
    assert parse_move(board, "o-o-o") == Move.from_uci("e1c1")


def test_parse_promotion_defaults_to_queen_in_uci():
    board = Board("3k4/4P3/8/8/8/8/8/4K3 w - - 0 1")
    assert parse_move(board, "e7e8") == Move.from_uci("e7e8q")
    assert parse_move(board, "e8=N") == Move.from_uci("e7e8n")


@pytest.mark.parametrize("text", ["", "e5", "Ke3", "hello", "e2e5"])
def test_parse_move_refuses_illegal_moves(text):
    with pytest.raises(ValueError):
        parse_move(Board(), text)


def test_b_is_a_pawn_file_not_a_bishop():
    assert parse_move(Board(), "b4") == Move.from_uci("b2b4")


def test_movetext_numbers_moves_and_handles_black_first():
    assert movetext("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", ["e4", "e5", "Nf3"]) == (
        "1. e4 e5 2. Nf3"
    )
    assert movetext("4k3/8/8/8/8/8/8/4K3 b - - 0 7", ["Kd7", "Kd2"]) == "7... Kd7 8. Kd2"


def test_pgn_has_headers_moves_and_result():
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    text = pgn(start, ["f3", "e5", "g4", "Qh4#"], "0-1", "You", "Computer (Hard)", date(2026, 10, 12))
    assert '[Date "2026.10.12"]' in text
    assert '[White "You"]' in text
    assert '[Result "0-1"]' in text
    assert "FEN" not in text
    assert text.strip().endswith("1. f3 e5 2. g4 Qh4# 0-1")


def test_pgn_records_a_custom_start_and_wraps_long_lines():
    start = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
    text = pgn(start, ["Kd2", "Kd7"] * 30, "*")
    assert f'[FEN "{start}"]' in text
    assert '[SetUp "1"]' in text
    assert all(len(line) <= 80 for line in text.splitlines())
