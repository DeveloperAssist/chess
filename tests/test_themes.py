import pygame
import pytest

from chessgame.themes import (
    BOARD_THEMES,
    PIECE_SETS,
    PieceArt,
    Settings,
    board_theme,
    find_piece_font,
    strong_font_file,
)


@pytest.fixture(autouse=True)
def screen():
    pygame.init()
    pygame.display.set_mode((10, 10))
    yield
    pygame.quit()


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    Settings(board="Ocean", pieces="Royal", coach=False).save(path)
    assert Settings.load(path) == Settings(board="Ocean", pieces="Royal", coach=False)


@pytest.mark.parametrize("text", ["not json", '{"board": "Plaid", "pieces": 7, "coach": "yes"}', "[]"])
def test_bad_settings_files_fall_back_to_defaults(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")
    assert Settings.load(path) == Settings()


def test_missing_settings_file_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "nothing.json") == Settings()


def test_board_themes_have_unique_names_and_a_fallback():
    names = [t.name for t in BOARD_THEMES]
    assert len(names) == len(set(names)) == 6
    assert board_theme("Wood").name == "Wood"
    assert board_theme("Plaid") is BOARD_THEMES[0]


@pytest.mark.parametrize("style", PIECE_SETS)
def test_every_piece_set_draws_all_twelve_pieces(style):
    art = PieceArt(48, find_piece_font(), style, strong_font_file())
    assert set(art.images) == set("KQRBNPkqrbnp")
    for image in art.images.values():
        assert image.get_size() == (48, 48)
        assert image.get_bounding_rect().width > 10  # something was drawn


def test_without_a_chess_font_every_style_uses_letters():
    art = PieceArt(40, None, "Neon")
    assert art.style == "Letters"
    assert art["q"].get_size() == (40, 40)


def test_white_and_black_pieces_look_different():
    art = PieceArt(48, find_piece_font(), "Classic")
    white, black = art["Q"], art["q"]
    centre = (24, 30)
    assert sum(white.get_at(centre)[:3]) != sum(black.get_at(centre)[:3])
