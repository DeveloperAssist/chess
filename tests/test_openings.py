import random

import pytest

from chessgame.ai import choose_move
from chessgame.board import Board, Move
from chessgame.game import Game
from chessgame.notation import parse_move
from chessgame.openings import LINES, NAMES, OpeningBook, get_book


def game_after(moves: str) -> Game:
    game = Game()
    for move in moves.split():
        game.play(move)
    return game


@pytest.mark.parametrize("opening", NAMES, ids=lambda o: o.name)
def test_every_named_opening_is_legal_and_recognised(opening):
    game = game_after(opening.moves)  # raises if any move is illegal
    named = get_book().name(game.fens)
    assert named is not None
    # Another entry may name the same position first (a transposition), but never a wrong family.
    assert named.name.split(":")[0].split(" Accepted")[0].split(" Declined")[0] in opening.name


@pytest.mark.parametrize(("moves", "weight"), LINES, ids=lambda x: str(x)[:30])
def test_every_line_is_legal(moves, weight):
    game_after(moves)
    assert weight >= 1


def test_every_family_has_an_idea():
    book = get_book()
    for opening in NAMES:
        assert book.idea(opening), opening.name


def test_names_follow_the_game():
    book = get_book()
    assert book.name(Game().fens) is None
    assert book.name(game_after("e4 e5 Nf3 Nc6 Bc4").fens).name == "Italian Game"
    assert book.name(game_after("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3").fens).name == (
        "Sicilian Defense: Najdorf Variation"
    )
    # After leaving the book, the last name found still describes the game.
    assert book.name(game_after("e4 e5 Nf3 Nc6 Bc4 h6 h3").fens).name == "Italian Game"


def test_transpositions_are_recognised():
    # The Queen's Gambit Declined, reached with a different move order.
    book = get_book()
    game = game_after("d4 Nf6 c4 e6 Nc3 d5")
    assert book.is_book(Board(game.fens[-2]), game.moves[-1])


def test_variation_ideas_fall_back_to_the_family():
    book = get_book()
    najdorf = next(o for o in NAMES if o.name == "Sicilian Defense: Open")
    assert book.idea(najdorf) == next(o for o in NAMES if o.name == "Sicilian Defense").idea


def test_book_moves_and_weights_from_the_start():
    moves = get_book().moves(Board())
    ucis = {m.uci() for m in moves}
    assert {"e2e4", "d2d4", "c2c4", "g1f3", "f2f4"} == ucis
    assert max(moves, key=moves.get) == Move.from_uci("e2e4")


def test_choice_follows_the_weights():
    book = get_book()
    rng = random.Random(1)
    picks = [book.choose(Board(), rng).uci() for _ in range(300)]
    assert picks.count("e2e4") > picks.count("d2d4") > picks.count("f2f4")


def test_out_of_book_means_no_book_move():
    board = Board()
    for text in ["a3", "h6"]:
        board.make(parse_move(board, text))
    assert get_book().choose(board, random.Random(0)) is None
    assert get_book().best(board) is None


def test_the_computer_plays_book_moves_then_thinks():
    first = choose_move(Board(), "hard", seed=4)
    assert first.book and first.seconds == 0
    assert get_book().is_book(Board(), first.move)
    searched = choose_move(Board(), "medium", seed=4, book=False)
    assert not searched.book


def test_a_small_custom_book():
    from chessgame.openings import Opening

    book = OpeningBook(names=(Opening("Test Opening", "e4 e5", "An idea."),), lines=(("e4 e5 Nf3", 2),))
    assert book.best(Board()) == Move.from_uci("e2e4")
    assert book.name(game_after("e4 e5").fens).name == "Test Opening"
