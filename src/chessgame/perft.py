"""Perft: the test that proves the move generator is right.

perft(depth) counts every possible sequence of ``depth`` moves from a position. Those counts are
known exactly for well-studied positions (20, 400, 8,902, 197,281 from the start), and a single
wrong rule (en passant, castling through check, a missed promotion...) changes them.
"""

from .board import Board


def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1
    moves = board.legal_moves()
    if depth == 1:
        return len(moves)  # no need to play the last move just to count it
    total = 0
    for move in moves:
        board.make(move)
        total += perft(board, depth - 1)
        board.unmake()
    return total


def divide(board: Board, depth: int) -> dict[str, int]:
    """perft split by first move, e.g. {'e2e4': 600, ...}. When a count is wrong, comparing this
    with a trusted engine shows which move hides the bug."""
    counts = {}
    for move in board.legal_moves():
        board.make(move)
        counts[move.uci()] = perft(board, depth - 1)
        board.unmake()
    return counts
