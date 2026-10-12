import pytest

from chessgame.board import BLACK, EMPTY, START_FEN, WHITE, Board, Move, square, square_name


def uci(board: Board) -> set[str]:
    return {m.uci() for m in board.legal_moves()}


def test_square_names_round_trip():
    assert square("a8") == 0
    assert square("h1") == 63
    assert square("e4") == 36
    assert all(square(square_name(s)) == s for s in range(64))
    with pytest.raises(ValueError):
        square("i9")


def test_start_position_fen_round_trip():
    board = Board()
    assert board.fen() == START_FEN
    assert board.turn == WHITE
    assert board.kings == {WHITE: square("e1"), BLACK: square("e8")}


@pytest.mark.parametrize(
    "fen",
    [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP w KQkq - 0 1",  # 7 rows
        "rnbqkbnr/pppppppp/9/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # 9 squares in a row
        "rnbq1bnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # no black king
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",  # bad turn
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkx - 0 1",  # bad castling
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",  # too short
        "rnbqkbnr/ppppXppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # unknown piece
    ],
)
def test_bad_fens_are_refused(fen):
    with pytest.raises(ValueError):
        Board(fen)


def test_castling_rights_need_the_king_and_rook_at_home():
    board = Board("4k3/8/8/8/8/8/8/4K2R w KQkq - 0 1")
    assert board.castling == "K"


def test_make_and_unmake_restore_every_position_exactly():
    board = Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    before = board.fen()
    for move in board.legal_moves():
        board.make(move)
        for reply in board.legal_moves():
            board.make(reply)
            board.unmake()
        board.unmake()
        assert board.fen() == before, move


def test_en_passant_capture_removes_the_pawn_beside():
    board = Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    assert "e5d6" in uci(board)
    board.make(Move.from_uci("e5d6"))
    assert board.squares[square("d5")] == EMPTY
    assert board.squares[square("d6")] == "P"
    board.unmake()
    assert board.squares[square("d5")] == "p"


def test_en_passant_square_is_set_after_a_double_step():
    board = Board()
    board.make(Move.from_uci("e2e4"))
    assert board.en_passant == square("e3")
    board.make(Move.from_uci("g8f6"))
    assert board.en_passant is None


def test_en_passant_that_would_expose_the_king_is_illegal():
    # Taking on d6 would remove both pawns from the 5th rank and leave the king in check.
    board = Board("8/8/8/K2pP2r/8/8/8/4k3 w - d6 0 1")
    assert "e5d6" not in uci(board)


def test_promotion_offers_four_pieces():
    board = Board("8/4P1k1/8/8/8/8/8/4K3 w - - 0 1")
    promotions = {m.promotion for m in board.legal_moves() if m.start == square("e7")}
    assert promotions == {"q", "r", "b", "n"}
    board.make(Move.from_uci("e7e8n"))
    assert board.squares[square("e8")] == "N"
    board.unmake()
    assert board.squares[square("e7")] == "P"


def test_castling_moves_the_rook_and_ends_the_rights():
    board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert {"e1g1", "e1c1"} <= uci(board)
    board.make(Move.from_uci("e1g1"))
    assert board.squares[square("f1")] == "R"
    assert board.squares[square("h1")] == EMPTY
    assert board.castling == "kq"
    board.unmake()
    assert board.squares[square("h1")] == "R"
    assert board.castling == "KQkq"


def test_no_castling_out_of_through_or_into_check():
    out_of = Board("4r1k1/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # rook gives check on the e-file
    through = Board("5rk1/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # f1 is attacked
    into = Board("6rk/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # g1 is attacked
    assert "e1g1" not in uci(out_of) and "e1c1" not in uci(out_of)
    assert "e1g1" not in uci(through) and "e1c1" in uci(through)
    assert "e1g1" not in uci(into)


def test_queen_side_castling_only_needs_b1_empty_not_safe():
    board = Board("1r2k3/8/8/8/8/8/8/R3K3 w Q - 0 1")  # b1 is attacked, the king never crosses it
    assert "e1c1" in uci(board)


def test_capturing_a_rook_ends_that_castling_right():
    board = Board("r3k2r/8/8/8/8/8/6B1/R3K2R w KQkq - 0 1")
    board.make(Move.from_uci("g2a8"))
    assert board.castling == "KQk"


def test_a_pinned_piece_cannot_leave_the_line():
    board = Board("4r1k1/8/8/8/8/8/4N3/4K3 w - - 0 1")
    assert not any(m.start == square("e2") for m in board.legal_moves())


def test_checkmate_and_stalemate():
    mate = Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    stale = Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert mate.is_checkmate() and not mate.is_stalemate()
    assert stale.is_stalemate() and not stale.is_checkmate()


@pytest.mark.parametrize(
    ("fen", "dead"),
    [
        ("8/8/8/4k3/8/8/8/4K3 w - - 0 1", True),  # king v king
        ("8/8/8/4k3/8/8/8/3BK3 w - - 0 1", True),  # king and bishop v king
        ("8/8/8/4k3/8/8/8/3NK3 w - - 0 1", True),  # king and knight v king
        ("8/8/8/1b2k3/8/8/8/3BK3 w - - 0 1", True),  # bishops on b5 and d1: both light squares
        ("8/8/8/2b1k3/8/8/8/3BK3 w - - 0 1", False),  # c5 is dark, d1 is light
        ("8/8/8/4k3/8/8/8/2NNK3 w - - 0 1", False),  # two knights (a mate exists)
        ("8/8/8/4k3/8/8/4P3/4K3 w - - 0 1", False),  # a pawn can promote
    ],
)
def test_insufficient_material(fen, dead):
    assert Board(fen).insufficient_material() is dead


def test_position_key_ignores_en_passant_nobody_can_use():
    board = Board()
    board.make(Move.from_uci("e2e4"))
    assert board.position_key().endswith(" b KQkq -")
    capturable = Board("4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1")
    assert capturable.position_key().endswith(" b - e3")


def test_move_uci_text():
    move = Move.from_uci("e7e8q")
    assert move == Move(square("e7"), square("e8"), "q")
    assert str(move) == "e7e8q"
    with pytest.raises(ValueError):
        Move.from_uci("e7e8x")
