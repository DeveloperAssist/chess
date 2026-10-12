"""The window, driven by fake mouse clicks and keys. SDL draws into memory (see conftest.py)."""

import pygame
import pytest

from chessgame.board import BLACK, WHITE, Board, Move, square
from chessgame.notation import parse_move
from chessgame.openings import get_book
from chessgame.themes import PIECE_SETS, Settings
from chessgame.ui import App, Layout


@pytest.fixture
def make_app(tmp_path):
    """Builds apps that draw offscreen, run the computer in this thread, and keep their settings
    in a temporary file (with the coach off unless a test turns it on)."""
    settings_path = tmp_path / "settings.json"
    Settings(coach=False).save(settings_path)
    apps = []

    def make(**options) -> App:
        defaults = {"square_size": 64, "threaded": False, "reply_delay": 0, "games_dir": tmp_path,
                    "settings_path": settings_path, "history_path": tmp_path / "history.json"}  # fmt: skip
        app = App(**(defaults | options))
        apps.append(app)
        app.draw()
        return app

    yield make
    for app in apps:
        app.analyst.close()
    pygame.quit()


def click(app: App, pos) -> None:
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
    app.update()
    app.draw()


def click_square(app: App, name: str) -> None:
    click(app, app.square_rect(square(name)).center)


def play(app: App, moves: str) -> None:
    for text in moves.split():
        app.play(parse_move(app.game.board, text), animate=False)
    app.draw()


def drag(app: App, start: str, end: str) -> None:
    a, b = app.square_rect(square(start)).center, app.square_rect(square(end)).center
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=a, button=1))
    app.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=b, rel=(0, 0), buttons=(1, 0, 0)))
    app.draw()  # draws the piece under the mouse
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=b, button=1))
    app.update()
    app.draw()


def press(app: App, label: str) -> None:
    button = next(b for b in app.buttons if b.label == label and app._visible(b))
    click(app, button.rect.center)


def key(app: App, k: int) -> None:
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=""))
    app.update()
    app.draw()


# --- Moving pieces ---------------------------------------------------------------------------


def test_click_a_piece_then_a_square_to_move(make_app):
    app = make_app(opponent="friend")
    click_square(app, "e2")
    assert app.selected == square("e2")
    assert app.targets(square("e2")) == {square("e3"), square("e4")}
    click_square(app, "e4")
    assert app.game.sans == ["e4"]
    assert app.selected is None


def test_drag_and_drop(make_app):
    app = make_app(opponent="friend")
    drag(app, "g1", "f3")
    assert app.game.sans == ["Nf3"]


def test_dropping_on_an_illegal_square_moves_nothing(make_app):
    app = make_app(opponent="friend")
    drag(app, "e2", "e5")
    assert app.game.moves == []


def test_cannot_move_the_other_sides_pieces(make_app):
    app = make_app(opponent="friend")
    click_square(app, "e7")
    assert app.selected is None


def test_clicking_a_selected_piece_again_puts_it_down(make_app):
    app = make_app(opponent="friend")
    click_square(app, "e2")
    click_square(app, "e2")
    assert app.selected is None


def test_promotion_asks_which_piece(make_app):
    app = make_app(opponent="friend", fen="7k/4P3/8/8/8/8/8/4K3 w - - 0 1")
    click_square(app, "e7")
    click_square(app, "e8")
    assert app.promotion == (square("e7"), square("e8"))
    assert app.game.moves == []
    knight = next(rect for piece, rect in app._promotion_choices() if piece == "N")
    click(app, knight.center)
    assert app.game.moves == [Move(square("e7"), square("e8"), "n")]
    assert app.game.sans == ["e8=N"]


def test_promotion_choice_can_be_cancelled(make_app):
    app = make_app(opponent="friend", fen="7k/4P3/8/8/8/8/8/4K3 w - - 0 1")
    click_square(app, "e7")
    click_square(app, "e8")
    key(app, pygame.K_ESCAPE)
    assert app.promotion is None and app.game.moves == []


def test_flipped_board_maps_squares_both_ways(make_app):
    app = make_app(opponent="friend")
    for flipped in (False, True):
        app.flipped = flipped
        for sq in range(64):
            assert app.square_at(app.square_rect(sq).center) == sq
    assert app.square_at((1, 1)) is None


def test_flip_button(make_app):
    app = make_app(opponent="friend")
    press(app, "Flip")
    assert app.flipped
    assert app.square_rect(square("h1")).topleft == app.layout.board.topleft


# --- The computer --------------------------------------------------------------------------------


def test_computer_replies_after_your_move(make_app):
    app = make_app(opponent="easy")
    click_square(app, "e2")
    click_square(app, "e4")
    app.wait_for_computer()
    assert len(app.game.moves) == 2
    assert app.game.turn == WHITE


def test_computer_moves_first_when_you_play_black(make_app):
    app = make_app(opponent="easy", human=BLACK)
    app.wait_for_computer()
    assert len(app.game.moves) == 1
    assert app.flipped


def test_threaded_computer(make_app):
    app = make_app(opponent="hard", threaded=True)
    click_square(app, "d2")
    click_square(app, "d4")
    app.wait_for_computer()
    assert len(app.game.moves) == 2


def test_the_computer_opens_with_book_moves(make_app):
    app = make_app(opponent="hard", human=BLACK)
    app.wait_for_computer()
    assert get_book().is_book(Board(app.game.start_fen), app.game.moves[0])


def test_the_same_seed_plays_the_same_game(make_app):
    games = []
    for _ in range(2):
        app = make_app(opponent="easy", seed=11)
        for start, end in (("e2", "e4"), ("g1", "f3"), ("f1", "c4"), ("d2", "d3")):
            if square(start) in {m.start for m in app.game.legal_moves()}:
                click_square(app, start)
                click_square(app, end)
                app.wait_for_computer()
        games.append(app.game.sans)
    assert games[0] == games[1] and len(games[0]) >= 6


def test_undo_against_the_computer_takes_back_both_moves(make_app):
    app = make_app(opponent="easy")
    click_square(app, "e2")
    click_square(app, "e4")
    app.wait_for_computer()
    press(app, "Undo")
    assert app.game.moves == []
    assert app.game.turn == WHITE


def test_undo_with_a_friend_takes_back_one_move(make_app):
    app = make_app(opponent="friend")
    click_square(app, "e2")
    click_square(app, "e4")
    key(app, pygame.K_u)
    assert app.game.moves == []


def test_switching_opponent_and_colour(make_app):
    app = make_app(opponent="friend")
    press(app, "Hard")
    assert app.opponent == "hard"
    press(app, "Easy")
    press(app, "Black")  # the computer now plays White, and moves
    app.wait_for_computer()
    assert app.human == BLACK and len(app.game.moves) == 1
    press(app, "Friend")
    press(app, "White")  # "You play" does nothing with a friend
    assert app.human == BLACK


def test_new_game_while_the_computer_thinks_ignores_its_answer(make_app):
    app = make_app(opponent="hard", threaded=True)
    click_square(app, "e2")
    click_square(app, "e4")
    press(app, "New game")
    app.wait_for_computer()
    assert app.game.moves == []


def test_a_move_played_while_the_computer_answers_cancels_its_answer(make_app):
    app = make_app(opponent="easy", reply_delay=60)
    click_square(app, "e2")
    click_square(app, "e4")  # the computer's answer waits a minute before it's shown
    app.play(parse_move(app.game.board, "e5"), animate=False)  # e.g. a script plays for Black
    app.update(now=float("inf"))
    assert app.game.sans == ["e4", "e5"] and app.pending is None


def test_save_pgn(make_app, tmp_path):
    app = make_app(opponent="medium")
    click_square(app, "e2")
    click_square(app, "e4")
    app.wait_for_computer()
    path = app.save_pgn()
    text = path.read_text(encoding="utf-8")
    assert path.parent == tmp_path
    assert '[White "You"]' in text and '[Black "Computer (Medium)"]' in text
    assert "1. e4 " in text
    assert app.toast is not None


# --- Themes and settings -------------------------------------------------------------------------


def test_settings_change_the_board_and_pieces_and_are_remembered(make_app, tmp_path):
    app = make_app(opponent="friend")
    press(app, "Settings")
    assert app.settings_open
    tiles = [rect for rect, _ in app._hits]  # 6 boards, 5 piece sets, coach on/off, done
    click(app, tiles[1].center)  # Wood
    click(app, tiles[6 + PIECE_SETS.index("Neon")].center)
    assert (app.settings.board, app.settings.pieces) == ("Wood", "Neon")
    assert app.theme.name == "Wood" and app.pieces.style == "Neon"
    key(app, pygame.K_ESCAPE)
    assert not app.settings_open
    remembered = Settings.load(tmp_path / "settings.json")
    assert (remembered.board, remembered.pieces) == ("Wood", "Neon")


def test_board_clicks_do_nothing_while_settings_are_open(make_app):
    app = make_app(opponent="friend")
    key(app, pygame.K_g)
    card = app._settings_card()
    click(app, (card.x + 5, card.bottom - 5))  # inside the card, on nothing
    assert app.settings_open and app.selected is None
    click(app, (2, 2))  # outside the card closes it
    assert not app.settings_open


def test_keys_cycle_board_and_pieces_and_toggle_the_coach(make_app):
    app = make_app(opponent="friend")
    key(app, pygame.K_t)
    key(app, pygame.K_p)
    key(app, pygame.K_c)
    assert app.settings.board == "Wood"
    assert app.settings.pieces == "Wood"
    assert app.settings.coach


@pytest.mark.parametrize("style", PIECE_SETS)
def test_every_piece_set_draws(make_app, style):
    app = make_app(opponent="friend")
    app.set_piece_set(style)
    app.draw()
    assert app.pieces["Q"].get_size() == (64, 64)


# --- The coach -------------------------------------------------------------------------------


def test_lightbulb_suggests_a_book_move_at_the_start(make_app):
    app = make_app(opponent="friend")
    press(app, "Hint")
    fen, move, text = app.suggest
    assert move == Move.from_uci("e2e4")
    assert "King's Pawn Opening" in text
    assert app._coach_message()[0] == "Suggested move"
    click_square(app, "e2")
    click_square(app, "e4")
    assert app.suggest is None  # a new position: the old suggestion goes


def test_lightbulb_out_of_book_finds_the_mate(make_app):
    app = make_app(
        opponent="friend", fen="r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    )
    key(app, pygame.K_h)
    app.wait_for_analysis()
    assert app.suggest[1] == Move.from_uci("h5f7")
    assert "checkmate" in app.suggest[2]


def test_coach_grades_every_move_and_flags_a_blunder(make_app):
    app = make_app(opponent="friend")
    app.set_coach(True)
    play(app, "e4 e5 Qh5 Nc6 Bc4 Nf6")
    app.wait_for_analysis()
    reviews = app.reviews()
    assert reviews[0].kind == "book"
    assert reviews[-1].kind == "blunder"
    header, _, body = app._coach_message()
    assert header == "Nf6: Blunder" and "Qxf7#" in body
    app.draw()  # the move list shows the "??"


def test_eval_bar_follows_the_analysis(make_app):
    app = make_app(opponent="friend", fen="4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    app.set_coach(True)
    app.wait_for_analysis()
    assert app.eval_shown > 0.9  # White is a queen up


def test_coach_works_in_the_background(make_app):
    app = make_app(opponent="friend", threaded=True)
    app.set_coach(True)
    play(app, "d4 d5 c4")
    app.wait_for_analysis()
    assert all(r is not None for r in app.reviews())


# --- The review ---------------------------------------------------------------------------------


def test_game_over_shows_a_summary_and_opens_the_review(make_app):
    app = make_app(opponent="friend")
    play(app, "f3 e5 g4 Qh4")
    assert app.game.outcome().reason == "checkmate"
    app.wait_for_analysis()  # the review needs every move, even with the coach off
    app.draw()
    lines, progress = app._summary_lines()
    assert progress == 1 and "blunder" in lines[0]
    review_button = app._hits[0][0]
    click(app, review_button.center)
    assert app.reviewing
    assert app.reviews()[app.review_ply].kind in ("inaccuracy", "mistake", "miss", "blunder")


def test_review_navigation(make_app):
    app = make_app(opponent="friend")
    play(app, "e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7")
    press(app, "Review")
    app.wait_for_analysis()
    assert app.reviewing
    press(app, "« First")
    assert app.review_ply == 0
    key(app, pygame.K_RIGHT)
    key(app, pygame.K_RIGHT)
    assert app.review_ply == 2
    press(app, "Next mistake ›")
    assert app.reviews()[app.review_ply].san == "Nf6"
    key(app, pygame.K_END)
    assert app.review_ply == len(app.game.moves)
    click_square(app, "a2")
    assert app.selected is None  # no moving pieces during the review
    press(app, "Back to game")
    assert not app.reviewing


def test_clicking_a_move_in_the_list_opens_the_review_there(make_app):
    app = make_app(opponent="friend")
    play(app, "d4 d5 c4 e6")
    rect, ply = app._move_cells[1]
    click(app, rect.center)
    assert app.reviewing and app.review_ply == ply == 1


def test_clicking_the_graph_jumps_to_that_move(make_app):
    app = make_app(opponent="friend")
    play(app, "d4 d5 c4 e6 Nc3 Nf6")
    press(app, "Review")
    graph = app.layout.graph
    click(app, (graph.right - 2, graph.centery))
    assert app.review_ply == len(app.game.moves)
    click(app, (graph.x + 1, graph.centery))
    assert app.review_ply == 0


def test_review_needs_moves(make_app):
    app = make_app(opponent="friend")
    press(app, "Review")
    assert not app.reviewing and app.toast is not None


def test_finished_games_against_the_computer_build_a_learning_curve(make_app, tmp_path):
    from chessgame.progress import GameRecord, load_history, record_game

    history = tmp_path / "history.json"
    record_game(history, GameRecord("old", "2026-10-01", "easy", "loss", 61.0, 2, 1, 0))
    app = make_app(opponent="easy", fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    click_square(app, "a1")
    click_square(app, "a8")  # Ra8#
    assert app.game.outcome().reason == "checkmate"
    app.wait_for_analysis()
    app.draw()  # the game-over card now shows the curve
    games = load_history(history)
    assert [g.result for g in games] == ["loss", "win"]
    assert games[-1].accuracy == 100.0 and games[-1].level == "easy"
    app.update()
    assert len(load_history(history)) == 2  # the same game is only counted once


def test_games_with_a_friend_are_not_recorded(make_app, tmp_path):
    from chessgame.progress import load_history

    app = make_app(opponent="friend")
    play(app, "f3 e5 g4 Qh4")
    app.wait_for_analysis()
    assert load_history(tmp_path / "history.json") == []


# --- Layout ----------------------------------------------------------------------------------


@pytest.mark.parametrize("s", [44, 64, 80])
def test_layout_fits_the_window(s):
    layout = Layout(s)
    width, height = layout.window
    assert layout.eval_bar.right < layout.board.x
    assert layout.board.right < layout.panel.x and layout.panel.right <= width
    assert layout.moves.height > s
    parts = [layout.title, layout.top_card, layout.moves, layout.coach, layout.bottom_card, *layout.rows]
    for upper, lower in zip(parts, parts[1:], strict=False):
        assert upper.bottom <= lower.top
    assert layout.rows[-1].bottom <= height
    assert layout.summary.bottom <= layout.graph.top < layout.graph.bottom <= layout.move_card.top
    assert layout.move_card.bottom <= layout.rows[0].top
