import pytest

from chessgame import cli
from chessgame.board import BLACK, Board
from chessgame.terminal import can_print_symbols, play_in_terminal, render


def scripted(*lines: str):
    """A fake `input`: hands out the lines one by one, then says the input has ended."""
    answers = iter(lines)

    def read(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    return read


def test_render_shows_pieces_and_coordinates():
    text = render(Board(), ascii_only=True)
    lines = text.splitlines()
    assert lines[0].split() == list("abcdefgh")
    assert lines[1].split() == ["8", *"rnbqkbnr", "8"]
    assert lines[8].split() == ["1", *"RNBQKBNR", "1"]
    assert "♔" in render(Board())


def test_symbols_only_where_the_terminal_can_show_them():
    class Stream:
        def __init__(self, encoding):
            self.encoding = encoding

    assert can_print_symbols(Stream("utf-8"))
    assert not can_print_symbols(Stream("cp1252"))
    assert not can_print_symbols(Stream(None))


def test_render_from_blacks_side():
    lines = render(Board(), white_at_bottom=False, ascii_only=True).splitlines()
    assert lines[0].split() == list("hgfedcba")
    assert lines[1].split() == ["1", *"RNBKQBNR", "1"]  # rank 1, read from h to a


def test_fools_mate_in_the_terminal_with_a_review():
    out: list[str] = []
    game = play_in_terminal("friend", read=scripted("f3", "e5", "g4", "Qh4"), write=out.append)
    assert game.outcome().reason == "checkmate"
    text = "\n".join(out)
    assert "Checkmate. Black wins." in text
    assert "Reviewing the game" in text
    assert "2. g4: g4 is a blunder. It allows mate in 1, starting with Qh4#." in text


def test_terminal_explains_illegal_moves_and_commands():
    out: list[str] = []
    commands = scripted("e5", "moves", "help", "e4", "hint", "review", "undo", "pgn", "quit")
    play_in_terminal("friend", read=commands, write=out.append)
    text = "\n".join(out)
    assert "'e5' is not a legal move here" in text
    assert "Nf3" in text  # from 'moves'
    assert "hint, undo" in text  # from 'help'
    assert "Opening: King's Pawn Opening" in text
    assert "Try e5: the main book move. It leads to the Open Game." in text  # from 'hint'
    assert "White: Accuracy 100%" in text  # from 'review'
    assert out[-1] == "Bye!"


def test_terminal_against_the_computer():
    out: list[str] = []
    game = play_in_terminal("easy", read=scripted("e4", "d4", "quit"), write=out.append)
    assert len(game.moves) == 4
    assert sum("Computer (Black) plays" in line for line in out) == 2


def test_terminal_computer_moves_first_for_black():
    out: list[str] = []
    game = play_in_terminal("easy", human=BLACK, read=scripted("hint", "quit"), write=out.append)
    assert len(game.moves) == 1
    assert any(line.startswith("Try ") for line in out)


def test_cli_perft(capsys):
    assert cli.main(["perft", "3"]) == 0
    out = capsys.readouterr().out
    assert "depth 3:" in out and "8,902" in out


def test_cli_perft_divide(capsys):
    cli.main(["perft", "2", "--divide"])
    out = capsys.readouterr().out
    assert "e2e4: 20" in out


def test_cli_refuses_a_bad_fen(capsys):
    assert cli.main(["--fen", "not a fen"]) == 2
    assert "doesn't work" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("medium", "w")),
        (["--friend"], ("friend", "w")),
        (["--black", "--level", "hard"], ("hard", "b")),
        (["play", "--level", "easy"], ("easy", "w")),
    ],
)
def test_cli_opens_the_window_with_the_right_options(monkeypatch, argv, expected):
    seen = []
    monkeypatch.setattr("chessgame.ui.play", lambda opponent, human, fen: seen.append((opponent, human)))
    assert cli.main(argv) == 0
    assert seen == [expected]
