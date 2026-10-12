"""The game window, drawn with pygame-ce.

The window only draws things and reacts to clicks. The chess lives in ``Game``, the computer player
in ``ai``, and the coach in ``analysis`` and ``coach``. Two background threads keep the window
smooth: one for the computer's move, one (the ``Analyst``) that grades every move.
"""

import contextlib
import math
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from .ai import LEVELS, Level, choose_move  # noqa: E402
from .analysis import (  # noqa: E402
    ANALYSIS,
    BAD,
    KINDS,
    REPLY,
    SUFFIX,
    Analyst,
    MoveReview,
    format_score,
    jobs_for,
    review_move,
    summarise,
    white_expected,
)
from .board import BLACK, EMPTY, FILES, START_FEN, WHITE, Board, Move, color_of, other  # noqa: E402
from .coach import chance, explain, suggestion  # noqa: E402
from .game import Game, Outcome  # noqa: E402
from .openings import get_book  # noqa: E402
from .progress import HISTORY_FILE, GameRecord, fingerprint, load_history, record_game, today  # noqa: E402
from .themes import (  # noqa: E402
    AMBER,
    BG,
    BOARD_THEMES,
    CARD,
    CYAN,
    GREEN,
    KIND_COLOURS,
    LINE,
    MUTED,
    PANEL,
    PIECE_SETS,
    RED,
    SETTINGS_FILE,
    TEXT,
    Fonts,
    PieceArt,
    Settings,
    board_theme,
    find_piece_font,
    strong_font_file,
)

# --- Layout --------------------------------------------------------------------------------------


def pick_square_size() -> int:
    """Squares as big as the screen comfortably allows (80 px on a 1080p screen)."""
    try:
        width, height = pygame.display.get_desktop_sizes()[0]
    except (pygame.error, IndexError):
        width, height = 1600, 900
    return max(44, min(80, (height - 150) // 9, (width - 80) // 15))


class Layout:
    """Where everything goes, worked out from the size of one square (``s``)."""

    def __init__(self, s: int) -> None:
        self.s = s
        pad = s // 2
        self.board = pygame.Rect(pad, pad, 8 * s, 8 * s)
        self.eval_bar = pygame.Rect(round(s * 0.13), pad, round(s * 0.24), 8 * s)
        width = round(4.6 * s)
        x = self.board.right + pad
        self.window = (x + width + pad, self.board.bottom + pad)
        self.panel = pygame.Rect(x, pad, width, 8 * s)
        gap, row, card = round(s * 0.1), round(s * 0.44), round(s * 0.72)

        # From the bottom of the panel upwards: 3 rows of buttons, a player card, the coach.
        y = self.panel.bottom
        self.rows: list[pygame.Rect] = []
        for _ in range(3):
            y -= row
            self.rows.insert(0, pygame.Rect(x, y, width, row))
            y -= gap
        self.bottom_card = pygame.Rect(x, y - card, width, card)
        y = self.bottom_card.top - gap
        self.coach = pygame.Rect(x, y - round(s * 1.24), width, round(s * 1.24))
        y = self.coach.top - gap

        # From the top down: the title and the other player card. The moves fill the middle.
        self.title = pygame.Rect(x, pad, width, round(s * 0.6))
        self.top_card = pygame.Rect(x, self.title.bottom + round(s * 0.12), width, card)
        top = self.top_card.bottom + gap
        self.moves = pygame.Rect(x, top, width, y - top)

        # The review uses the space under the title instead.
        review_top = self.title.bottom + round(s * 0.12)
        self.summary = pygame.Rect(x, review_top, width, round(s * 2.45))
        self.graph = pygame.Rect(x, self.summary.bottom + gap, width, round(s * 1.05))
        card_top = self.graph.bottom + gap
        self.move_card = pygame.Rect(x, card_top, width, self.rows[0].top - gap - card_top)


# --- Small UI pieces -------------------------------------------------------------------------------


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: Callable[[], None]
    selected: Callable[[], bool] = lambda: False
    enabled: Callable[[], bool] = lambda: True
    mode: str = "play"  # shown in "play" mode, "review" mode, or "any"
    icon: str = ""  # "gear" or "bulb": drawn instead of the label


@dataclass
class Drag:
    square: int
    was_selected: bool
    start_pos: tuple[int, int]
    moved: bool = False


@dataclass
class Animation:
    piece: str
    start: int
    end: int
    began: float
    duration: float = 0.16


@dataclass
class Toast:
    text: str
    until: float


@dataclass
class Worker:
    """The computer's move, worked out in a background thread."""

    token: int  # which game state it was started for (see App.token)
    stop: threading.Event = field(default_factory=threading.Event)


def wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
    """Split text into lines that fit ``width`` pixels."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.size(trial)[0] > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return [*lines, line] if line else lines


# --- The app -----------------------------------------------------------------------------------------


class App:
    def __init__(
        self,
        *,
        opponent: str = "medium",  # "friend", "easy", "medium" or "hard"
        human: str = WHITE,
        fen: str = START_FEN,
        square_size: int | None = None,
        threaded: bool = True,
        reply_delay: float = 0.45,
        games_dir: Path | None = None,
        settings_path: Path | None = SETTINGS_FILE,
        history_path: Path | None = HISTORY_FILE,
        analysis_levels: tuple[Level, Level] = (ANALYSIS, REPLY),
    ) -> None:
        pygame.init()
        self.s = square_size or pick_square_size()
        self.layout = Layout(self.s)
        self.screen = pygame.display.set_mode(self.layout.window)
        pygame.display.set_caption("Chess in Python · Developers Assist")
        self.settings_path = settings_path
        self.settings = Settings.load(settings_path) if settings_path else Settings()
        self.piece_font = find_piece_font()
        self.letter_font = strong_font_file()
        pygame.display.set_icon(PieceArt(32, self.piece_font)["N"])
        self.fonts = Fonts(self.s)
        self._load_pieces()

        self.opponent = opponent
        self.human = human
        self.flipped = human == BLACK
        self.threaded = threaded
        self.reply_delay = reply_delay
        self.games_dir = games_dir or Path.cwd() / "games"
        self.levels = analysis_levels
        self.analyst = Analyst(threaded=threaded, levels=analysis_levels)
        self.history_path = history_path
        self.history = load_history(history_path) if history_path else []
        self._recorded = ""  # the game already added to the history

        self.game = Game(fen)
        self.token = 0  # bumped on new game / undo / setting changes; stale results are ignored
        self.worker: Worker | None = None
        self.results: queue.Queue[tuple[Worker, object]] = queue.Queue()
        self.ready_at = 0.0  # don't show the computer's reply before this time
        self.pending: tuple[Worker, object] | None = None

        self.selected: int | None = None
        self.drag: Drag | None = None
        self.promotion: tuple[int, int] | None = None  # (start, end) waiting for a piece choice
        self.animation: Animation | None = None
        self.toast: Toast | None = None
        self.suggest: tuple[str, Move, str] | None = None  # (position, move, why) from the lightbulb
        self.suggest_wanted = False
        self.review_ply: int | None = None  # the move being reviewed; None while playing
        self._review_jump = False
        self.settings_open = False
        self.eval_shown = 0.5  # the evaluation bar, slides towards the latest analysis
        self.mouse = (0, 0)
        self.running = True
        self._cursor = pygame.SYSTEM_CURSOR_ARROW
        self._review_cache: dict[tuple[str, str], MoveReview] = {}
        self._reviews_key: tuple | None = None
        self._reviews: list[MoveReview | None] = []
        self._view: tuple[int, Board] | None = None
        self._hits: list[tuple[pygame.Rect, Callable[[], None]]] = []  # overlay click areas
        self._move_cells: list[tuple[pygame.Rect, int]] = []
        self._last_tick = time.perf_counter()
        self.buttons = self._make_buttons()
        self._check_glow = self._make_check_glow()
        self._changed()

    # -- Who plays what --

    @property
    def vs_computer(self) -> bool:
        return self.opponent != "friend"

    @property
    def reviewing(self) -> bool:
        return self.review_ply is not None

    @property
    def theme(self):
        return board_theme(self.settings.board)

    def computer_to_move(self) -> bool:
        return self.vs_computer and self.game.turn != self.human

    def can_touch(self) -> bool:
        """Can the person at the keyboard move pieces right now?"""
        return (
            not self.reviewing
            and not self.settings_open
            and self.game.outcome() is None
            and self.worker is None
            and self.pending is None
            and not self.computer_to_move()
        )

    def _load_pieces(self) -> None:
        style = self.settings.pieces
        self.pieces = PieceArt(self.s, self.piece_font, style, self.letter_font)
        self.mini_pieces = PieceArt(round(self.s * 0.3), self.piece_font, style, self.letter_font)
        self._previews: dict[str, PieceArt] = {}

    # -- Buttons --

    def _make_buttons(self) -> list[Button]:
        layout, s = self.layout, self.s
        rows, gap = layout.rows, round(s * 0.08)
        buttons: list[Button] = []

        def split(row: pygame.Rect, count: int, left: int = 0) -> list[pygame.Rect]:
            width = (row.width - left - gap * (count - 1)) / count
            return [
                pygame.Rect(round(row.x + left + i * (width + gap)), row.y, round(width), row.height)
                for i in range(count)
            ]

        gear = pygame.Rect(0, 0, round(s * 0.48), round(s * 0.48))
        gear.midright = (layout.title.right, layout.title.centery)
        buttons.append(Button(gear, "Settings", self.open_settings, mode="any", icon="gear"))
        bulb = pygame.Rect(0, 0, round(s * 0.62), round(s * 0.62))
        bulb.midleft = (layout.coach.x + round(s * 0.14), layout.coach.centery)
        buttons.append(Button(bulb, "Hint", self.ask_hint, enabled=self.can_touch, icon="bulb"))

        # While playing.
        actions = [("New game", self.new_game), ("Undo", self.undo), ("Flip", self.flip),
                   ("Review", self.open_review)]  # fmt: skip
        for rect, (label, action) in zip(split(rows[0], 4), actions, strict=True):
            buttons.append(Button(rect, label, action))
        label_width = round(s * 0.95)
        opponents = [("Friend", "friend"), ("Easy", "easy"), ("Medium", "medium"), ("Hard", "hard")]
        for rect, (label, value) in zip(split(rows[1], 4, label_width), opponents, strict=True):
            buttons.append(Button(rect, label, lambda v=value: self.set_opponent(v),
                                  selected=lambda v=value: self.opponent == v))  # fmt: skip
        for rect, (label, value) in zip(split(rows[2], 2, label_width), [("White", WHITE), ("Black", BLACK)],
                                        strict=True):  # fmt: skip
            buttons.append(Button(rect, label, lambda v=value: self.set_human(v),
                                  selected=lambda v=value: self.vs_computer and self.human == v,
                                  enabled=lambda: self.vs_computer))  # fmt: skip

        # While reviewing.
        review = [
            [("« First", lambda: self.review_to(0)), ("‹ Back", lambda: self.review_step(-1)),
             ("Next ›", lambda: self.review_step(1)), ("Last »", lambda: self.review_to(10**6))],
            [("‹ Previous mistake", lambda: self.review_key_moment(-1)),
             ("Next mistake ›", lambda: self.review_key_moment(1))],
            [("Save PGN", self.save_pgn), ("Back to game", self.close_review)],
        ]  # fmt: skip
        for row, specs in zip(rows, review, strict=True):
            for rect, (label, action) in zip(split(row, len(specs)), specs, strict=True):
                buttons.append(Button(rect, label, action, mode="review"))
        return buttons

    def _visible(self, button: Button) -> bool:
        return button.mode == "any" or button.mode == ("review" if self.reviewing else "play")

    # -- Actions (buttons and keys) --

    def new_game(self) -> None:
        self._cancel_worker()
        self.game = Game(self.game.start_fen)
        self.review_ply = None
        self._reset_view()
        self._changed()

    def undo(self) -> None:
        if not self.game.moves or self.reviewing:
            return
        thinking = self.worker is not None
        self._cancel_worker()
        self.game.undo()
        # Against the computer, take back its reply too, so it's your turn again.
        if self.vs_computer and not thinking:
            while self.game.moves and self.game.turn != self.human:
                self.game.undo()
        self._reset_view()
        self._changed()

    def flip(self) -> None:
        self.flipped = not self.flipped

    def set_opponent(self, opponent: str) -> None:
        if opponent == self.opponent:
            return
        self._cancel_worker()
        self.opponent = opponent
        self._show(
            "Two players on one screen." if opponent == "friend"
            else f"Computer level: {LEVELS[opponent].name}."
        )  # fmt: skip
        self._changed()

    def set_human(self, color: str) -> None:
        if color == self.human:
            return
        self._cancel_worker()
        self.human = color
        self.flipped = color == BLACK
        self.selected = None
        self._changed()

    def ask_hint(self) -> None:
        """The lightbulb: "What should I play?" Uses the analysis of this position (or waits for it)."""
        if not self.can_touch():
            return
        self.suggest_wanted = True
        self._changed()
        self._try_suggestion()

    def save_pgn(self) -> Path:
        names = {WHITE: "White", BLACK: "Black"}
        if self.vs_computer:
            names = {self.human: "You", other(self.human): f"Computer ({LEVELS[self.opponent].name})"}
        self.games_dir.mkdir(parents=True, exist_ok=True)
        path = self.games_dir / f"chess-{datetime.now():%Y-%m-%d-%H%M%S}.pgn"
        path.write_text(self.game.pgn(names[WHITE], names[BLACK]), encoding="utf-8")
        self._show(f"Saved {path.parent.name}/{path.name}")
        return path

    # -- Settings --

    def open_settings(self) -> None:
        self.settings_open = not self.settings_open
        self.selected, self.drag = None, None

    def set_board_theme(self, name: str) -> None:
        self.settings.board = name
        self._save_settings()

    def set_piece_set(self, name: str) -> None:
        self.settings.pieces = name
        self._load_pieces()
        self._save_settings()

    def set_coach(self, on: bool) -> None:
        self.settings.coach = on
        self._save_settings()
        self._changed()

    def _save_settings(self) -> None:
        if self.settings_path:
            self.settings.save(self.settings_path)

    # -- Review --

    def open_review(self) -> None:
        if not self.game.moves:
            self._show("Play a few moves first, then review them.")
            return
        self._cancel_worker()
        self.selected, self.promotion, self.drag, self.suggest = None, None, None, None
        self.review_ply = 0
        self._review_jump = True  # go to the first mistake as soon as the grades are in
        self._changed()
        self._jump_to_first_moment()

    def _jump_to_first_moment(self) -> None:
        reviews = self.reviews()
        if not self._review_jump or not reviews or not all(reviews):
            return
        self._review_jump = False
        moments = self._key_moments() or self._key_moments(anyone=True)
        if moments:
            self.review_ply = moments[0]

    def close_review(self) -> None:
        self.review_ply = None
        self._changed()

    def review_to(self, ply: int) -> None:
        if self.reviewing:
            self._review_jump = False  # you're looking around yourself now
            self.review_ply = max(0, min(len(self.game.moves), ply))

    def review_step(self, delta: int) -> None:
        if self.reviewing:
            self.review_to(self.review_ply + delta)

    def _key_moments(self, anyone: bool = False) -> list[int]:
        """Moves worth a second look: inaccuracies, mistakes, missed chances and blunders (only
        yours when you play the computer, unless ``anyone``)."""
        mine_only = self.vs_computer and not anyone
        return [
            r.ply for r in self.reviews() if r and r.kind in BAD and (not mine_only or r.color == self.human)
        ]

    def review_key_moment(self, direction: int) -> None:
        if not self.reviewing:
            return
        self._review_jump = False
        moments = self._key_moments()
        later = [p for p in moments if (p > self.review_ply if direction > 0 else p < self.review_ply)]
        if later:
            self.review_ply = later[0] if direction > 0 else later[-1]
        else:
            self._show("No more mistakes that way." if moments else "No mistakes found. Well played!")

    def reviews(self) -> list[MoveReview | None]:
        """Every move's grade so far (None where the analysis isn't ready yet). Grades are kept by
        position and move, so they're only worked out once."""
        key = (self.analyst.version, tuple(self.game.fens))
        if key != self._reviews_key:
            self._reviews_key = key
            reviews = []
            for ply, move in enumerate(self.game.moves):
                cache_key = (self.game.fens[ply], move.uci())
                review = self._review_cache.get(cache_key)
                if review is None:
                    review = review_move(self.game, ply, self.analyst.cache, self.levels)
                    if review is not None:
                        self._review_cache[cache_key] = review
                reviews.append(review)
            self._reviews = reviews
        return self._reviews

    def view_board(self) -> Board:
        """The board on screen: the game, or the position being reviewed."""
        if not self.reviewing:
            return self.game.board
        if (
            self._view is None
            or self._view[0] != self.review_ply
            or self._view[1].fen() != self.game.fens[self.review_ply]
        ):
            self._view = (self.review_ply, Board(self.game.fens[self.review_ply]))
        return self._view[1]

    # -- Playing moves --

    def play(self, move: Move, animate: bool = True) -> None:
        if self.worker or self.pending:
            self._cancel_worker()  # a move from elsewhere makes the computer's answer out of date
        piece = self.game.board.squares[move.start]
        self.game.play(move)
        self.selected, self.promotion = None, None
        if animate:
            self.animation = Animation(piece, move.start, move.end, time.perf_counter())
        self.ready_at = time.perf_counter() + self.reply_delay
        self._changed()

    def _try_move(self, start: int, end: int, animate: bool) -> bool:
        options = [m for m in self.game.legal_moves() if m.start == start and m.end == end]
        if not options:
            return False
        if len(options) > 1:  # a pawn reaching the last rank: ask which piece it becomes
            self.promotion = (start, end)
            self.selected = start
        else:
            self.play(options[0], animate)
        return True

    def targets(self, start: int) -> set[int]:
        return {m.end for m in self.game.legal_moves() if m.start == start}

    def _changed(self) -> None:
        """After anything that changes the game: tell the analyst, maybe start the computer."""
        if self.suggest and self.suggest[0] != self.game.fens[-1]:
            self.suggest = None
        self.analyst.want(self._jobs())
        self._maybe_start_computer()

    def _jobs(self) -> list:
        """What the analyst should work on. The end-of-game review needs every move, even with the
        coach turned off."""
        jobs = []
        if self.settings.coach or self.reviewing or self.game.outcome() is not None:
            jobs = jobs_for(self.game, self.levels)
        if self.suggest_wanted:
            jobs.insert(0, (self.game.fens[-1], self.levels[0]))
        return jobs

    def _try_suggestion(self) -> None:
        if not self.suggest_wanted:
            return
        board, fen = self.game.board, self.game.fens[-1]
        analysis = self.analyst.cache.get(fen, self.levels[0])
        if analysis is None and get_book().best(board) is None:
            return  # still thinking
        found = suggestion(board, analysis, get_book().name(self.game.fens))
        self.suggest_wanted = False
        if found:
            self.suggest = (fen, *found)

    # -- The computer, in a background thread --

    def _maybe_start_computer(self) -> None:
        if (
            self.computer_to_move()
            and self.game.outcome() is None
            and self.worker is None
            and self.pending is None
            and not self.reviewing
        ):
            self._start_worker()

    def _start_worker(self) -> None:
        worker = Worker(self.token)
        board = self.game.board.copy()
        seen = self.game.positions()
        level = self.opponent
        self.worker = worker
        self.analyst.allowed.clear()  # the analyst waits while the computer thinks

        def run() -> None:
            result = choose_move(board, level, stop=worker.stop, seen=seen)
            self.results.put((worker, result))

        if self.threaded:
            threading.Thread(target=run, daemon=True, name="chess-computer").start()
        else:
            run()

    def _cancel_worker(self) -> None:
        if self.worker:
            self.worker.stop.set()
        self.worker, self.pending = None, None
        self.token += 1
        self.analyst.allowed.set()

    def wait_for_computer(self, timeout: float = 30) -> None:
        """Block until the computer's move is played (for tests)."""
        end = time.perf_counter() + timeout
        while (self.worker or self.pending) and time.perf_counter() < end:
            self.update(now=float("inf"))
            time.sleep(0.01)

    def wait_for_analysis(self, timeout: float = 60) -> None:
        """Block until the analyst has nothing left to do (for tests)."""
        end = time.perf_counter() + timeout
        while self.analyst.pending() and time.perf_counter() < end:
            time.sleep(0.01)
        self.update(now=float("inf"))

    def update(self, now: float | None = None) -> None:
        """Pick up finished background work, and move animations along."""
        clock = time.perf_counter()
        now = clock if now is None else now
        while not self.results.empty():
            worker, result = self.results.get()
            if worker is self.worker and worker.token == self.token:
                self.worker, self.pending = None, (worker, result)
                self.analyst.allowed.set()
        if self.pending and now >= self.ready_at:
            _, result = self.pending
            self.pending = None
            if result is not None and result.move in self.game.legal_moves():
                self.play(result.move)
        self._try_suggestion()
        if self.animation and clock - self.animation.began > self.animation.duration:
            self.animation = None
        if self.toast and clock > self.toast.until:
            self.toast = None
        self._record_finished_game()
        if self.reviewing:
            self._jump_to_first_moment()
        # The evaluation bar glides to its new value instead of jumping.
        target = white_expected(self._shown_fen(), self.analyst.cache, self.levels[0])
        if target is not None:
            step = min(1.0, (clock - self._last_tick) * 8)
            self.eval_shown += (target - self.eval_shown) * (1.0 if now == float("inf") else step)
        self._last_tick = clock

    def _record_finished_game(self) -> None:
        """Once a game against the computer is over and fully graded, add it to your history."""
        outcome = self.game.outcome()
        if outcome is None or not self.vs_computer or not self.history_path:
            return
        game_id = fingerprint(self.game.start_fen, [m.uci() for m in self.game.moves])
        reviews = self.reviews()
        if game_id == self._recorded or not reviews or not all(reviews):
            return
        summary = summarise(reviews, self.human)
        if not summary.moves:
            return
        result = "draw" if outcome.winner is None else ("win" if outcome.winner == self.human else "loss")
        counts = summary.counts
        record = GameRecord(game_id, today(), self.opponent, result, round(summary.accuracy, 1),
                            counts["blunder"], counts["mistake"], counts["miss"])  # fmt: skip
        self.history = record_game(self.history_path, record)
        self._recorded = game_id

    def _shown_fen(self) -> str:
        return self.game.fens[self.review_ply] if self.reviewing else self.game.fens[-1]

    # -- Mouse and keyboard --

    def handle(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            if self.drag and math.dist(event.pos, self.drag.start_pos) > self.s * 0.08:
                self.drag.moved = True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.mouse = event.pos
            self._press(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mouse = event.pos
            self._release(event.pos)
        elif event.type == pygame.KEYDOWN:
            self._key(event.key)

    def _key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.settings_open:
                self.settings_open = False
            elif self.reviewing:
                self.close_review()
            self.selected, self.promotion, self.drag = None, None, None
            return
        if self.reviewing:
            moves = {pygame.K_LEFT: lambda: self.review_step(-1), pygame.K_RIGHT: lambda: self.review_step(1),
                     pygame.K_HOME: lambda: self.review_to(0),
                     pygame.K_END: lambda: self.review_to(len(self.game.moves)),
                     pygame.K_UP: lambda: self.review_key_moment(-1),
                     pygame.K_DOWN: lambda: self.review_key_moment(1)}  # fmt: skip
            if key in moves:
                moves[key]()
                return
        keys = {
            pygame.K_n: self.new_game,
            pygame.K_u: self.undo,
            pygame.K_z: self.undo,
            pygame.K_f: self.flip,
            pygame.K_h: self.ask_hint,
            pygame.K_s: self.save_pgn,
            pygame.K_r: lambda: self.close_review() if self.reviewing else self.open_review(),
            pygame.K_g: self.open_settings,
            pygame.K_t: lambda: self.set_board_theme(_next(BOARD_NAMES, self.settings.board)),
            pygame.K_p: lambda: self.set_piece_set(_next(list(PIECE_SETS), self.settings.pieces)),
            pygame.K_c: lambda: self.set_coach(not self.settings.coach),
        }  # fmt: skip
        if key in keys:
            keys[key]()

    def _press(self, pos: tuple[int, int]) -> None:
        if self.settings_open:
            for rect, action in self._hits:
                if rect.collidepoint(pos):
                    action()
                    return
            if not self._settings_card().collidepoint(pos):
                self.settings_open = False
            return
        if self.promotion:
            self._choose_promotion(pos)
            return
        for button in self.buttons:
            if self._visible(button) and button.rect.collidepoint(pos):
                if button.enabled():
                    button.action()
                return
        for rect, action in self._hits:  # game-over card buttons
            if rect.collidepoint(pos):
                action()
                return
        for rect, ply in self._move_cells:
            if rect.collidepoint(pos):
                if not self.reviewing:
                    self.open_review()
                self.review_to(ply)
                return
        if self.reviewing:
            if self.layout.graph.collidepoint(pos) and self.game.moves:
                share = (pos[0] - self.layout.graph.x) / max(1, self.layout.graph.width)
                self.review_to(round(share * len(self.game.moves)))
            return
        sq = self.square_at(pos)
        if sq is None or not self.can_touch():
            self.selected = None
            return
        if self.selected is not None and sq in self.targets(self.selected):
            self._try_move(self.selected, sq, animate=True)
            return
        piece = self.game.board.squares[sq]
        if piece != EMPTY and color_of(piece) == self.game.turn:
            self.drag = Drag(sq, self.selected == sq, pos)
            self.selected = sq
        else:
            self.selected = None

    def _release(self, pos: tuple[int, int]) -> None:
        drag, self.drag = self.drag, None
        if drag is None:
            return
        sq = self.square_at(pos)
        if sq is not None and sq != drag.square and self._try_move(drag.square, sq, animate=False):
            return
        if sq == drag.square and drag.was_selected and not drag.moved:
            self.selected = None  # clicking a selected piece again puts it down

    def _choose_promotion(self, pos: tuple[int, int]) -> None:
        start, end = self.promotion
        for piece, rect in self._promotion_choices():
            if rect.collidepoint(pos):
                self.promotion = None
                self.play(Move(start, end, piece.lower()))
                return
        self.promotion = None  # clicked elsewhere: cancel

    # -- Squares on screen --

    def square_rect(self, sq: int) -> pygame.Rect:
        row, col = divmod(sq, 8)
        if self.flipped:
            row, col = 7 - row, 7 - col
        board = self.layout.board
        return pygame.Rect(board.x + col * self.s, board.y + row * self.s, self.s, self.s)

    def square_at(self, pos: tuple[int, int]) -> int | None:
        board = self.layout.board
        col, row = (pos[0] - board.x) // self.s, (pos[1] - board.y) // self.s
        if not (0 <= row < 8 and 0 <= col < 8):
            return None
        if self.flipped:
            row, col = 7 - row, 7 - col
        return row * 8 + col

    # -- Drawing --

    def draw(self) -> None:
        self._hits = []
        self.screen.fill(BG)
        self._draw_eval_bar()
        self._draw_board()
        self._draw_panel()
        if self.settings_open:
            self._draw_settings()
        self._update_cursor()

    def _draw_eval_bar(self) -> None:
        if not (self.settings.coach or self.reviewing):
            return
        bar, s = self.layout.eval_bar, self.s
        radius = bar.width // 2
        pygame.draw.rect(self.screen, (40, 46, 56), bar, border_radius=radius)
        white_height = round(bar.height * self.eval_shown)
        white = pygame.Rect(bar.x, bar.bottom - white_height, bar.width, white_height)
        if self.flipped:
            white.top = bar.top
        if white_height > 0:
            pygame.draw.rect(self.screen, (236, 239, 244), white, border_radius=radius)
        pygame.draw.line(self.screen, CYAN, (bar.x - 2, bar.centery), (bar.right + 1, bar.centery), 1)
        found = self.analyst.cache.get(self._shown_fen(), self.levels[0])
        if found is not None:
            score = found.score if Board(self._shown_fen()).turn == WHITE else -found.score
            label = self.fonts.tiny.render(format_score(score), True, MUTED)
            self.screen.blit(label, label.get_rect(midtop=(bar.centerx, bar.bottom + s * 0.06)))

    def _draw_board(self) -> None:
        screen, s, board, theme = self.screen, self.s, self.view_board(), self.theme
        frame = self.layout.board.inflate(round(s * 0.12), round(s * 0.12))
        pygame.draw.rect(screen, LINE, frame, border_radius=round(s * 0.08))

        if self.reviewing:
            last = self.game.moves[self.review_ply - 1] if self.review_ply else None
        else:
            last = self.game.last_move
        lit = {last.start, last.end} if last else set()
        for sq in range(64):
            rect = self.square_rect(sq)
            light = sum(divmod(sq, 8)) % 2 == 0
            pygame.draw.rect(screen, theme.light if light else theme.dark, rect)
            if sq in lit:
                self._tint(rect, theme.highlight, 80)
            if sq == self.selected:
                self._tint(rect, theme.highlight, 140)
        if board.in_check():
            screen.blit(self._check_glow, self.square_rect(board.kings[board.turn]))
        self._draw_coordinates()

        anim = None if self.reviewing else self.animation
        dragging = self.drag.square if self.drag and self.drag.moved else None
        for sq, piece in enumerate(board.squares):
            if piece == EMPTY or sq == dragging or (anim and sq == anim.end):
                continue
            screen.blit(self.pieces[piece], self.square_rect(sq))

        if self.selected is not None and self.can_touch():
            self._draw_targets(self.selected)
        if self.reviewing:
            self._draw_review_arrows()
        elif self.suggest and self.suggest[0] == self.game.fens[-1]:
            self._draw_arrow(self.suggest[1], GREEN)
        if anim:
            t = min(1.0, (time.perf_counter() - anim.began) / anim.duration)
            t = 1 - (1 - t) ** 3  # ease out: fast start, gentle landing
            a = pygame.Vector2(self.square_rect(anim.start).topleft)
            b = pygame.Vector2(self.square_rect(anim.end).topleft)
            piece = board.squares[anim.end] if board.squares[anim.end] != EMPTY else anim.piece
            screen.blit(self.pieces[piece], a.lerp(b, t))
        if dragging is not None:
            image = self.pieces[board.squares[dragging]]
            screen.blit(image, image.get_rect(center=self.mouse))

        if self.promotion:
            self._draw_promotion()
        elif not self.reviewing and (outcome := self.game.outcome()) is not None:
            self._draw_game_over(outcome)
        if self.toast:
            self._draw_toast(self.toast.text)

    def _draw_review_arrows(self) -> None:
        if self.review_ply >= len(self.game.moves):
            return
        review = self.reviews()[self.review_ply]
        played = self.game.moves[self.review_ply]
        if review and review.best and review.best != played:
            self._draw_arrow(review.best, GREEN)
        colour = KIND_COLOURS[review.kind] if review else MUTED
        self._draw_arrow(played, colour)

    def _tint(self, rect: pygame.Rect, color: tuple[int, int, int], alpha: int) -> None:
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((*color, alpha))
        self.screen.blit(overlay, rect)

    def _make_check_glow(self) -> pygame.Surface:
        s = self.s
        glow = pygame.Surface((s, s), pygame.SRCALPHA)
        for i in range(12, 0, -1):
            pygame.draw.circle(glow, (*RED, round(200 * (1 - i / 12) ** 0.8)), (s / 2, s / 2), s * 0.06 * i)
        return glow

    def _draw_coordinates(self) -> None:
        s, font, theme = self.s, self.fonts.coord, self.theme
        for i in range(8):
            # Rank numbers down the left edge, file letters along the bottom edge.
            rank_sq = (7 - i if self.flipped else i) * 8 + (7 if self.flipped else 0)
            file_sq = (0 if self.flipped else 7) * 8 + (7 - i if self.flipped else i)
            for sq, text, corner in ((rank_sq, str(8 - rank_sq // 8), "top"),
                                     (file_sq, FILES[file_sq % 8], "bottom")):  # fmt: skip
                light = sum(divmod(sq, 8)) % 2 == 0
                label = font.render(text, True, theme.dark if light else theme.light)
                rect = self.square_rect(sq)
                if corner == "top":
                    self.screen.blit(label, (rect.x + s * 0.05, rect.y + s * 0.02))
                else:
                    self.screen.blit(label, label.get_rect(bottomright=(rect.right - s * 0.05, rect.bottom)))

    def _draw_targets(self, start: int) -> None:
        s = self.s
        layer = pygame.Surface((s, s), pygame.SRCALPHA)
        for end in self.targets(start):
            layer.fill((0, 0, 0, 0))
            if self.game.board.squares[end] != EMPTY:
                pygame.draw.circle(layer, (15, 23, 32, 90), (s / 2, s / 2), s * 0.47, round(s * 0.08))
            else:
                pygame.draw.circle(layer, (15, 23, 32, 90), (s / 2, s / 2), s * 0.15)
            self.screen.blit(layer, self.square_rect(end))

    def _draw_arrow(self, move: Move, colour) -> None:
        s = self.s
        a = pygame.Vector2(self.square_rect(move.start).center)
        b = pygame.Vector2(self.square_rect(move.end).center)
        if a == b:
            return
        direction = (b - a).normalize()
        side = pygame.Vector2(-direction.y, direction.x)
        head, half = s * 0.42, s * 0.11
        neck = b - direction * head
        a = a + direction * s * 0.25
        shape = [a + side * half, neck + side * half, neck + side * half * 2.6, b,
                 neck - side * half * 2.6, neck - side * half, a - side * half]  # fmt: skip
        layer = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(layer, (*colour, 190), shape)
        self.screen.blit(layer, (0, 0))

    def _promotion_choices(self) -> list[tuple[str, pygame.Rect]]:
        """Four squares on the promotion file, from the last rank towards the middle."""
        start, end = self.promotion
        white = self.game.board.squares[start].isupper()
        pieces = "QRBN" if white else "qrbn"
        rect = self.square_rect(end)
        step = self.s if rect.y == self.layout.board.y else -self.s
        return [(p, rect.move(0, i * step)) for i, p in enumerate(pieces)]

    def _draw_promotion(self) -> None:
        self._tint(self.layout.board, BG, 150)
        for piece, rect in self._promotion_choices():
            hover = rect.collidepoint(self.mouse)
            fill = CYAN if hover else self.theme.light
            pygame.draw.rect(self.screen, fill, rect.inflate(-4, -4), border_radius=self.s // 2)
            self.screen.blit(self.pieces[piece], rect)

    def _summary_lines(self) -> tuple[list[str], float]:
        """The end-of-game summary, and how much of the game is analysed (0 to 1)."""
        reviews = self.reviews()
        done = sum(r is not None for r in reviews)
        progress = done / len(reviews) if reviews else 1.0
        if progress < 1:
            return [], progress
        complete = [r for r in reviews if r]
        if self.vs_computer:
            return [f"You: {summarise(complete, self.human).line()}"], 1.0
        return [
            f"White: {summarise(complete, WHITE).line()}",
            f"Black: {summarise(complete, BLACK).line()}",
        ], 1.0

    def _draw_game_over(self, outcome: Outcome) -> None:
        if self.animation:
            return  # let the last move land first
        s, fonts = self.s, self.fonts
        self._tint(self.layout.board, BG, 120)
        box = pygame.Rect(0, 0, round(s * 6.2), round(s * 3.75))
        box.center = self.layout.board.center
        pygame.draw.rect(self.screen, PANEL, box, border_radius=round(s * 0.18))
        pygame.draw.rect(self.screen, CYAN, box, 2, border_radius=round(s * 0.18))
        title = outcome.reason.capitalize() if outcome.winner else "Draw"
        if outcome.winner and self.vs_computer:
            line = "You win!" if outcome.winner == self.human else "The computer wins."
        elif outcome.winner:
            line = f"{'White' if outcome.winner == WHITE else 'Black'} wins."
        else:
            line = f"By {outcome.reason}."
        self._text(title, fonts.banner, CYAN, midtop=(box.centerx, box.y + s * 0.22))
        self._text(line, fonts.body, TEXT, midtop=(box.centerx, box.y + s * 0.82))

        lines, progress = self._summary_lines()
        y = box.y + s * 1.32
        if progress < 1:
            self._text("Reviewing your game…", fonts.small, MUTED, midtop=(box.centerx, y))
            track = pygame.Rect(0, 0, round(s * 3.6), round(s * 0.1))
            track.midtop = (box.centerx, round(y + s * 0.3))
            pygame.draw.rect(self.screen, LINE, track, border_radius=track.height)
            done = track.copy()
            done.width = max(track.height, round(track.width * progress))
            pygame.draw.rect(self.screen, CYAN, done, border_radius=track.height)
        for text in lines:
            self._text(text, fonts.small, TEXT, midtop=(box.centerx, y))
            y += s * 0.27
        if self.vs_computer and self._recorded and len(self.history) >= 2:
            self._draw_learning_curve(pygame.Rect(box.x + round(s * 0.5), round(y + s * 0.1),
                                                  box.width - s, round(s * 0.62)))  # fmt: skip

        width, height, gap = round(s * 2.2), round(s * 0.46), round(s * 0.16)
        review = pygame.Rect(0, 0, width, height)
        review.bottomright = (box.centerx - gap // 2, box.bottom - round(s * 0.24))
        new = review.copy()
        new.left = box.centerx + gap // 2
        for rect, label, action, primary in ((review, "Review game", self.open_review, True),
                                             (new, "New game", self.new_game, False)):  # fmt: skip
            hover = rect.collidepoint(self.mouse)
            fill = CYAN if primary else (LINE if hover else CARD)
            pygame.draw.rect(self.screen, fill, rect, border_radius=round(s * 0.1))
            if not primary:
                pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.1))
            self._text(label, fonts.small_strong, BG if primary else TEXT, center=rect.center)
            self._hits.append((rect, action))

    def _draw_learning_curve(self, rect: pygame.Rect) -> None:
        """Your accuracy in your last games against the computer: your learning curve."""
        s, fonts = self.s, self.fonts
        recent = self.history[-10:]
        average = sum(r.accuracy for r in recent) / len(recent)
        label = f"Your last {len(recent)} games: average {average:.0f}%, this game {recent[-1].accuracy:.0f}%"
        self._text(label, fonts.small, MUTED, midtop=(rect.centerx, rect.y))
        chart = pygame.Rect(rect.x, rect.y + round(s * 0.24), rect.width, rect.height - round(s * 0.24))
        step = chart.width / max(1, len(recent) - 1)
        low = max(0.0, min(r.accuracy for r in recent) - 10)  # zoom in on your range of results
        span = max(1.0, 100 - low)
        points = [
            (chart.x + i * step, chart.bottom - chart.height * (r.accuracy - low) / span)
            for i, r in enumerate(recent)
        ]
        pygame.draw.line(self.screen, LINE, (chart.x, chart.bottom), (chart.right, chart.bottom), 1)
        pygame.draw.lines(self.screen, CYAN, False, points, 2)
        for point, record in zip(points, recent, strict=True):
            colour = GREEN if record.result == "win" else RED if record.result == "loss" else MUTED
            pygame.draw.circle(self.screen, colour, point, s * 0.05)
        pygame.draw.circle(self.screen, AMBER, points[-1], s * 0.08, 2)

    def _draw_toast(self, text: str) -> None:
        label = self.fonts.body.render(text, True, TEXT)
        box = label.get_rect().inflate(self.s * 0.5, self.s * 0.25)
        box.midbottom = (self.layout.board.centerx, self.layout.board.bottom - self.s * 0.25)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=box.height // 2)
        pygame.draw.rect(self.screen, LINE, box, 1, border_radius=box.height // 2)
        self.screen.blit(label, label.get_rect(center=box.center))

    # -- The panel on the right --

    def _draw_panel(self) -> None:
        layout, fonts, s = self.layout, self.fonts, self.s
        x = layout.panel.x
        first, second = ("Game", " review") if self.reviewing else ("Chess", " in Python")
        title = fonts.title.render(first, True, TEXT)
        self.screen.blit(title, (x, layout.title.y))
        self._text(second, fonts.title, CYAN, topleft=(x + title.get_width(), layout.title.y))
        self._text("Developers Assist", fonts.small, MUTED, topleft=(x, layout.title.y + s * 0.4))

        self._move_cells = []
        if self.reviewing:
            self._draw_summary(layout.summary)
            self._draw_graph(layout.graph)
            self._draw_move_card(layout.move_card)
        else:
            top, bottom = (WHITE, BLACK) if self.flipped else (BLACK, WHITE)
            self._draw_player(layout.top_card, top)
            self._draw_player(layout.bottom_card, bottom)
            self._draw_moves(layout.moves)
            self._draw_coach(layout.coach)
            for label, row in (("Opponent", layout.rows[1]), ("You play", layout.rows[2])):
                self._text(label, fonts.small, MUTED, midleft=(row.x, row.centery))
        for button in self.buttons:
            if self._visible(button):
                self._draw_button(button)

    def _player_name(self, color: str) -> tuple[str, str]:
        side = "White" if color == WHITE else "Black"
        if not self.vs_computer:
            return side, "Player"
        if color == self.human:
            return "You", side
        return "Computer", f"{side} · {LEVELS[self.opponent].name}"

    def _draw_player(self, rect: pygame.Rect, color: str) -> None:
        s, fonts = self.s, self.fonts
        to_move = self.game.turn == color and self.game.outcome() is None
        pygame.draw.rect(self.screen, CARD, rect, border_radius=round(s * 0.12))
        border = CYAN if to_move else LINE
        pygame.draw.rect(self.screen, border, rect, 2 if to_move else 1, border_radius=round(s * 0.12))
        chip = pygame.Rect(0, 0, round(s * 0.24), round(s * 0.24))
        chip.midleft = (rect.x + s * 0.16, rect.y + s * 0.22)
        pygame.draw.rect(
            self.screen, (250, 251, 252) if color == WHITE else (30, 36, 45), chip, border_radius=5
        )
        pygame.draw.rect(self.screen, MUTED, chip, 1, border_radius=5)
        name, detail = self._player_name(color)
        if to_move and self.vs_computer and color != self.human:
            detail = "thinking" + "." * (1 + int(time.perf_counter() * 3) % 3)
        name_label = self._text(name, fonts.strong, TEXT, midleft=(chip.right + s * 0.12, chip.centery))
        self._text(detail, fonts.small, MUTED, midleft=(name_label.right + s * 0.1, chip.centery))
        if to_move and self.game.board.in_check():
            self._text("Check!", fonts.small_strong, RED, midright=(rect.right - s * 0.16, chip.centery))

        # The pieces this player has taken, and how far ahead in material they are.
        taken = self.game.captured(other(color))
        x = rect.x + s * 0.12
        y = rect.bottom - s * 0.36
        step = self.mini_pieces.size * 0.62
        for piece in taken:
            self.screen.blit(self.mini_pieces[piece], (x, y))
            x += step
        lead = self.game.material() * (1 if color == WHITE else -1)
        if lead > 0:
            self._text(
                f"+{lead}",
                fonts.small,
                MUTED,
                midleft=(x + self.mini_pieces.size * 0.5, y + self.mini_pieces.size / 2),
            )

    def _draw_moves(self, rect: pygame.Rect) -> None:
        s, fonts = self.s, self.fonts
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=round(s * 0.12))
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.12))
        opening = get_book().name(self.game.fens)
        header_y = rect.y + s * 0.12
        if opening:
            self._book_icon(rect.x + s * 0.2, header_y + s * 0.03)
            text = self._fit(opening.name, fonts.small_strong, rect.width - round(s * 0.76))
            self._text(text, fonts.small_strong, KIND_COLOURS["book"], topleft=(rect.x + s * 0.56, header_y))
        else:
            self._text("Moves", fonts.small_strong, MUTED, topleft=(rect.x + s * 0.2, header_y))
        list_top = round(header_y + s * 0.34)
        self._draw_move_list(
            pygame.Rect(rect.x, list_top, rect.width, rect.bottom - list_top - round(s * 0.08))
        )

    def _draw_move_list(self, rect: pygame.Rect, selected: int | None = None) -> None:
        s, fonts = self.s, self.fonts
        sans = self.game.sans
        if not sans:
            self._text("Your moves appear here.", fonts.small, MUTED, topleft=(rect.x + s * 0.2, rect.y))
            return
        reviews = self.reviews()
        first_black = self.game.start_fen.split()[1] == BLACK
        number = int(self.game.start_fen.split()[5])
        cells = ([None] if first_black else []) + list(range(len(sans)))
        rows = [cells[i : i + 2] for i in range(0, len(cells), 2)]
        line_height = round(s * 0.29)
        fits = max(1, rect.height // line_height)
        focus = len(cells) - 1 if selected is None else selected + (1 if first_black else 0)
        first_row = max(
            0, min(len(rows) - fits, focus // 2 - fits + 2 if selected is not None else len(rows) - fits)
        )
        latest = len(sans) - 1
        y = rect.y
        for r in range(first_row, min(len(rows), first_row + fits)):
            self._text(f"{number + r}.", fonts.mono, MUTED, topleft=(rect.x + s * 0.2, y))
            for c, ply in enumerate(rows[r]):
                x = rect.x + s * (0.95 + c * 1.6)
                if ply is None:
                    self._text("…", fonts.mono, MUTED, topleft=(x, y))
                    continue
                review = reviews[ply] if ply < len(reviews) else None
                show_grade = review is not None and (self.settings.coach or self.reviewing)
                text = sans[ply] + (SUFFIX.get(review.kind, "") if show_grade else "")
                colour = TEXT
                if show_grade and review.kind in BAD + ("book",):
                    colour = KIND_COLOURS[review.kind]
                cell = pygame.Rect(round(x - s * 0.08), y - 1, round(s * 1.45), line_height)
                if ply == selected or (selected is None and ply == latest):
                    pygame.draw.rect(self.screen, LINE, cell, border_radius=round(s * 0.06))
                self._text(text, fonts.mono, colour, topleft=(x, y))
                self._move_cells.append((cell, ply))
            y += line_height

    def _draw_coach(self, rect: pygame.Rect) -> None:
        s, fonts = self.s, self.fonts
        pygame.draw.rect(self.screen, CARD, rect, border_radius=round(s * 0.12))
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.12))
        header, colour, body = self._coach_message()
        left = rect.x + round(s * 0.92)
        width = rect.right - round(s * 0.16) - left
        y = rect.y + s * 0.12
        self._text(
            self._fit(header, fonts.small_strong, width), fonts.small_strong, colour, topleft=(left, y)
        )
        y += s * 0.27
        lines = wrap(body, fonts.small, width)
        if len(lines) > 4:  # too long for the card: end the fourth line with "…"
            lines = [*lines[:3], self._fit(lines[3] + " " + " ".join(lines[4:]), fonts.small, width)]
        for line in lines:
            self._text(line, fonts.small, TEXT, topleft=(left, y))
            y += s * 0.2

    def _coach_message(self) -> tuple[str, tuple[int, int, int], str]:
        """What the coach card says: a suggestion, feedback on the last move, or the opening."""
        game, book = self.game, get_book()
        if self.suggest and self.suggest[0] == game.fens[-1]:
            return "Suggested move", GREEN, self.suggest[2]
        if self.suggest_wanted:
            return "Looking for a good move…", CYAN, ""
        outcome = game.outcome()
        if outcome:
            return "Game over", AMBER, f"{outcome.describe()} Press Review to see every move graded."
        if not self.settings.coach:
            body = "Turn it on in Settings (the gear) to grade every move. The lightbulb works either way."
            return "Coach is off", MUTED, body
        reviews = self.reviews()
        if reviews:
            last = reviews[-1]
            if (
                self.vs_computer
                and last
                and last.color != self.human
                and last.kind in ("mistake", "miss", "blunder")
            ):
                return f"The computer slipped: {last.label.lower()}", KIND_COLOURS[last.kind], chance(last)
            # Feedback on your own last move (against the computer), or on the last move (friends).
            mine = len(reviews) - 1
            if self.vs_computer and self._mover(mine) != self.human:
                mine -= 1
            review = reviews[mine] if mine >= 0 else None
            if review is not None:
                if review.kind == "book":
                    opening = book.name(game.fens[: mine + 2])
                    idea = f" {book.idea(opening)}" if opening else ""
                    return (
                        f"{review.san}: book move",
                        KIND_COLOURS["book"],
                        f"{opening.name if opening else 'Opening theory'}.{idea}",
                    )
                return f"{review.san}: {review.label}", KIND_COLOURS[review.kind], explain(review)
            if mine >= 0:
                return "Analysing your move…", CYAN, ""
        opening = book.name(game.fens)
        if opening:
            return opening.name, KIND_COLOURS["book"], book.idea(opening)
        return "Your coach", CYAN, "Make a move and I'll grade it. Stuck? The lightbulb shows a good move."

    # -- The review panel --

    def _draw_summary(self, rect: pygame.Rect) -> None:
        s, fonts = self.s, self.fonts
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=round(s * 0.12))
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.12))
        reviews = [r for r in self.reviews() if r]
        columns = [(WHITE, "You" if self.vs_computer and self.human == WHITE else "White"),
                   (BLACK, "You" if self.vs_computer and self.human == BLACK else "Black")]  # fmt: skip
        if self.vs_computer:
            columns = [(c, "You" if c == self.human else "Computer") for c, _ in columns]
        col_x = [rect.right - s * 1.75, rect.right - s * 0.7]
        y = rect.y + s * 0.1
        total = len(self.game.moves)
        status = "Every move graded" if len(reviews) == total else f"Analysing… {len(reviews)}/{total} moves"
        self._text(status, fonts.small_strong, MUTED, topleft=(rect.x + s * 0.18, y))
        for (_, name), x in zip(columns, col_x, strict=True):
            self._text(name, fonts.small_strong, TEXT, midtop=(x, y))
        y += s * 0.27
        summaries = [summarise(reviews, c) for c, _ in columns]
        self._text("Accuracy", fonts.small, TEXT, topleft=(rect.x + s * 0.18, y))
        for summary, x in zip(summaries, col_x, strict=True):
            text = f"{summary.accuracy:.0f}%" if summary.moves else "–"
            self._text(text, fonts.small_strong, CYAN, midtop=(x, y))
        y += s * 0.25
        for kind in KINDS:
            self._badge(kind, rect.x + s * 0.28, y + s * 0.1)
            self._text(LABEL_PLURAL[kind], fonts.small, TEXT, topleft=(rect.x + s * 0.48, y))
            for summary, x in zip(summaries, col_x, strict=True):
                self._text(str(summary.counts[kind]), fonts.small_strong, KIND_COLOURS[kind], midtop=(x, y))
            y += s * 0.2

    def _graph_points(self, rect: pygame.Rect) -> list[tuple[float, float] | None]:
        fens = self.game.fens
        count = max(1, len(fens) - 1)
        points = []
        for i, fen in enumerate(fens):
            value = white_expected(fen, self.analyst.cache, self.levels[0])
            x = rect.x + rect.width * i / count
            points.append(None if value is None else (x, rect.bottom - rect.height * value))
        return points

    def _draw_graph(self, rect: pygame.Rect) -> None:
        """The advantage curve: White's share of the game after every move (the bigger the light
        area, the better for White)."""
        s = self.s
        pygame.draw.rect(self.screen, (40, 46, 56), rect, border_radius=round(s * 0.1))
        inner = rect.inflate(-round(s * 0.16), -round(s * 0.16))
        points = [p for p in self._graph_points(inner) if p]
        if len(points) >= 2:
            shape = [(points[0][0], inner.bottom), *points, (points[-1][0], inner.bottom)]
            pygame.draw.polygon(self.screen, (226, 232, 240), shape)
            pygame.draw.lines(self.screen, CYAN, False, points, 2)
        pygame.draw.line(self.screen, MUTED, (inner.x, inner.centery), (inner.right, inner.centery), 1)
        all_points = self._graph_points(inner)
        for review in self.reviews():
            if review and review.kind in BAD and all_points[review.ply + 1]:
                pygame.draw.circle(
                    self.screen, KIND_COLOURS[review.kind], all_points[review.ply + 1], s * 0.06
                )
        if self.game.moves:
            x = inner.x + inner.width * self.review_ply / len(self.game.moves)
            pygame.draw.line(self.screen, AMBER, (x, rect.y + 2), (x, rect.bottom - 3), 2)

    def _draw_move_card(self, rect: pygame.Rect) -> None:
        s, fonts = self.s, self.fonts
        pygame.draw.rect(self.screen, CARD, rect, border_radius=round(s * 0.12))
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.12))
        ply = self.review_ply
        width = rect.width - round(s * 0.36)
        x, y = rect.x + s * 0.18, rect.y + s * 0.14
        if ply >= len(self.game.moves):
            outcome = self.game.outcome()
            self._text("Final position", fonts.strong, TEXT, topleft=(x, y))
            body = outcome.describe() if outcome else "The game isn't over yet. Back to game to play on."
        else:
            review = self.reviews()[ply]
            number = ply // 2 + 1 if self.game.start_fen.split()[1] == WHITE else (ply + 1) // 2 + 1
            dots = "." if Board(self.game.fens[ply]).turn == WHITE else "..."
            header = f"{number}{dots} {self.game.sans[ply]}"
            label = self._text(header, fonts.strong, TEXT, topleft=(x, y))
            if review is None:
                self._text("analysing…", fonts.small, MUTED, midleft=(label.right + s * 0.2, label.centery))
                body = ""
            else:
                self._badge(review.kind, label.right + s * 0.25, label.centery)
                self._text(review.label, fonts.small_strong, KIND_COLOURS[review.kind],
                           midleft=(label.right + s * 0.42, label.centery))  # fmt: skip
                body = explain(review)
                if review.best and review.best != review.move:
                    body += " Green arrow: the best move."
        y += s * 0.36
        lines = wrap(body, fonts.small, width)
        for line in lines[: max(1, int((rect.bottom - y) // (s * 0.21)))]:
            self._text(line, fonts.small, TEXT, topleft=(x, y))
            y += s * 0.21

    # -- Settings --

    def _settings_card(self) -> pygame.Rect:
        card = pygame.Rect(0, 0, round(self.s * 8.6), round(self.s * 5.95))
        card.center = (self.layout.window[0] // 2, self.layout.window[1] // 2)
        return card

    def _draw_settings(self) -> None:
        s, fonts = self.s, self.fonts
        self._hits = []
        dim = pygame.Surface(self.layout.window, pygame.SRCALPHA)
        dim.fill((*BG, 170))
        self.screen.blit(dim, (0, 0))
        card = self._settings_card()
        pygame.draw.rect(self.screen, PANEL, card, border_radius=round(s * 0.2))
        pygame.draw.rect(self.screen, LINE, card, 1, border_radius=round(s * 0.2))
        x0, y = card.x + round(s * 0.4), card.y + round(s * 0.3)
        inner = card.width - round(s * 0.8)
        self._text("Settings", fonts.title, TEXT, topleft=(x0, y))
        self._text("Esc to close · T, P and C change these from the keyboard", fonts.small, MUTED,
                   bottomright=(card.right - s * 0.4, y + s * 0.34))  # fmt: skip
        y += round(s * 0.75)

        self._text("Board", fonts.small_strong, MUTED, topleft=(x0, y))
        y += round(s * 0.3)
        gap = round(s * 0.16)
        tile_w = (inner - gap * (len(BOARD_THEMES) - 1)) // len(BOARD_THEMES)
        for i, theme in enumerate(BOARD_THEMES):
            tile = pygame.Rect(x0 + i * (tile_w + gap), y, tile_w, round(s * 0.95))
            half_w, half_h = tile.width // 2, tile.height // 2
            for j, (dx, dy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
                colour = theme.light if j in (0, 3) else theme.dark
                pygame.draw.rect(self.screen, colour, (tile.x + dx * half_w, tile.y + dy * half_h,
                                                       tile.width - half_w if dx else half_w,
                                                       tile.height - half_h if dy else half_h))  # fmt: skip
            chosen = self.settings.board == theme.name
            pygame.draw.rect(self.screen, CYAN if chosen else LINE, tile.inflate(6, 6), 3 if chosen else 1,
                             border_radius=round(s * 0.08))  # fmt: skip
            self._text(
                theme.name,
                fonts.small,
                TEXT if chosen else MUTED,
                midtop=(tile.centerx, tile.bottom + s * 0.08),
            )
            self._hits.append((tile.inflate(6, 6), lambda n=theme.name: self.set_board_theme(n)))
        y += round(s * 1.45)

        self._text("Pieces", fonts.small_strong, MUTED, topleft=(x0, y))
        y += round(s * 0.3)
        tile_w = (inner - gap * (len(PIECE_SETS) - 1)) // len(PIECE_SETS)
        theme = self.theme
        for i, name in enumerate(PIECE_SETS):
            art = self._previews.get(name)
            if art is None:
                art = self._previews[name] = PieceArt(
                    round(s * 0.62), self.piece_font, name, self.letter_font
                )
            tile = pygame.Rect(x0 + i * (tile_w + gap), y, tile_w, round(s * 0.95))
            pygame.draw.rect(self.screen, theme.light, tile.inflate(0, 0))
            pygame.draw.rect(
                self.screen, theme.dark, (tile.centerx, tile.y, tile.right - tile.centerx, tile.height)
            )
            self.screen.blit(art["K"], art["K"].get_rect(center=(tile.x + tile.width * 0.27, tile.centery)))
            self.screen.blit(art["n"], art["n"].get_rect(center=(tile.x + tile.width * 0.73, tile.centery)))
            chosen = self.settings.pieces == name
            pygame.draw.rect(self.screen, CYAN if chosen else LINE, tile.inflate(6, 6), 3 if chosen else 1,
                             border_radius=round(s * 0.08))  # fmt: skip
            self._text(
                name, fonts.small, TEXT if chosen else MUTED, midtop=(tile.centerx, tile.bottom + s * 0.08)
            )
            self._hits.append((tile.inflate(6, 6), lambda n=name: self.set_piece_set(n)))
        y += round(s * 1.45)

        self._text("Coach", fonts.small_strong, MUTED, topleft=(x0, y + s * 0.1))
        for i, (label, value) in enumerate((("On", True), ("Off", False))):
            rect = pygame.Rect(x0 + round(s * 0.9) + i * round(s * 1.05), y, round(s * 0.95), round(s * 0.44))
            chosen = self.settings.coach == value
            pygame.draw.rect(self.screen, CYAN if chosen else CARD, rect, border_radius=round(s * 0.1))
            if not chosen:
                pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=round(s * 0.1))
            self._text(label, fonts.small, BG if chosen else TEXT, center=rect.center)
            self._hits.append((rect, lambda v=value: self.set_coach(v)))
        self._text("Evaluation bar, and a grade for every move as you play.", fonts.small, MUTED,
                   midleft=(x0 + round(s * 3.1), y + s * 0.22))  # fmt: skip

        done = pygame.Rect(0, 0, round(s * 1.8), round(s * 0.48))
        done.bottomright = (card.right - round(s * 0.4), card.bottom - round(s * 0.3))
        pygame.draw.rect(self.screen, CYAN, done, border_radius=round(s * 0.1))
        self._text("Done", fonts.small_strong, BG, center=done.center)
        self._hits.append((done, self.open_settings))

    # -- Little drawing helpers --

    def _draw_button(self, button: Button) -> None:
        radius = round(self.s * 0.1)
        enabled, selected = button.enabled(), button.selected()
        hover = enabled and button.rect.collidepoint(self.mouse)
        if button.icon == "bulb":
            fill = AMBER if enabled and hover else ((60, 52, 24) if enabled else CARD)
            pygame.draw.circle(self.screen, fill, button.rect.center, button.rect.width / 2)
            pygame.draw.circle(
                self.screen, AMBER if enabled else LINE, button.rect.center, button.rect.width / 2, 2
            )
            self._bulb_icon(
                button.rect.center, button.rect.width * 0.3, BG if hover else (AMBER if enabled else MUTED)
            )
            return
        if button.icon == "gear":
            colour = TEXT if hover else MUTED
            self._gear_icon(button.rect.center, button.rect.width * 0.3, colour)
            return
        fill = CYAN if selected else (LINE if hover else CARD)
        pygame.draw.rect(self.screen, fill, button.rect, border_radius=radius)
        if not selected:
            pygame.draw.rect(self.screen, LINE, button.rect, 1, border_radius=radius)
        colour = BG if selected else (TEXT if enabled else (70, 80, 92))
        self._text(button.label, self.fonts.small, colour, center=button.rect.center)

    def _bulb_icon(self, centre, r: float, colour) -> None:
        cx, cy = centre
        pygame.draw.circle(self.screen, colour, (cx, cy - r * 0.25), r * 0.75)
        base = pygame.Rect(0, 0, round(r * 0.8), round(r * 0.55))
        base.midtop = (round(cx), round(cy + r * 0.3))
        pygame.draw.rect(self.screen, colour, base, border_radius=2)
        pygame.draw.line(self.screen, colour, (cx - r * 0.3, cy + r * 1.0), (cx + r * 0.3, cy + r * 1.0), 2)

    def _gear_icon(self, centre, r: float, colour) -> None:
        cx, cy = centre
        for i in range(8):
            angle = i * math.pi / 4
            a = (cx + math.cos(angle) * r * 0.9, cy + math.sin(angle) * r * 0.9)
            b = (cx + math.cos(angle) * r * 1.35, cy + math.sin(angle) * r * 1.35)
            pygame.draw.line(self.screen, colour, a, b, max(2, round(r * 0.45)))
        pygame.draw.circle(self.screen, colour, centre, r)
        pygame.draw.circle(self.screen, BG, centre, r * 0.45)

    def _book_icon(self, x: float, y: float) -> None:
        s, colour = self.s, KIND_COLOURS["book"]
        w, h = s * 0.13, s * 0.17
        left = [(x, y), (x + w, y + h * 0.12), (x + w, y + h), (x, y + h * 0.88)]
        right = [(2 * x + 2 * w + 2 - px, py) for px, py in left]  # the mirror image
        pygame.draw.polygon(self.screen, colour, left)
        pygame.draw.polygon(self.screen, colour, right)

    def _badge(self, kind: str, x: float, y: float) -> None:
        """A small coloured circle with a symbol, for a kind of move."""
        s, colour = self.s, KIND_COLOURS[kind]
        r = s * 0.1
        pygame.draw.circle(self.screen, colour, (x, y), r)
        symbol = {
            "inaccuracy": "?!",
            "mistake": "?",
            "miss": "×",
            "blunder": "??",
            "excellent": "!",
            "good": "✓",
        }
        if kind == "best":
            pygame.draw.lines(
                self.screen,
                BG,
                False,
                [(x - r * 0.45, y), (x - r * 0.1, y + r * 0.4), (x + r * 0.5, y - r * 0.4)],
                2,
            )
        elif kind == "book":
            pygame.draw.rect(self.screen, BG, (x - r * 0.45, y - r * 0.4, r * 0.9, r * 0.8), 1)
        elif kind == "good":
            pygame.draw.lines(
                self.screen,
                BG,
                False,
                [(x - r * 0.4, y), (x - r * 0.1, y + r * 0.3), (x + r * 0.4, y - r * 0.3)],
                1,
            )
        else:
            label = self.fonts.tiny.render(symbol[kind], True, BG)
            if label.get_width() > r * 1.9:
                label = pygame.transform.smoothscale_by(label, r * 1.9 / label.get_width())
            self.screen.blit(label, label.get_rect(center=(x, y)))

    def _text(self, text: str, font: pygame.font.Font, colour, **where) -> pygame.Rect:
        label = font.render(text, True, colour)
        rect = label.get_rect(**where)
        self.screen.blit(label, rect)
        return rect

    def _fit(self, text: str, font: pygame.font.Font, width: int) -> str:
        """Shorten text with '…' until it fits."""
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def _show(self, text: str, seconds: float = 2.5) -> None:
        self.toast = Toast(text, time.perf_counter() + seconds)

    def _mover(self, ply: int) -> str:
        """Who played move number ``ply`` (0 is the first move of this game)."""
        first = self.game.start_fen.split()[1]
        return first if ply % 2 == 0 else other(first)

    def _reset_view(self) -> None:
        self.selected, self.drag, self.promotion, self.animation = None, None, None, None
        self.suggest, self.suggest_wanted = None, False

    def _update_cursor(self) -> None:
        over_button = any(
            self._visible(b) and b.enabled() and b.rect.collidepoint(self.mouse) for b in self.buttons
        ) or any(rect.collidepoint(self.mouse) for rect, _ in self._hits)
        sq = self.square_at(self.mouse)
        over_piece = (
            sq is not None
            and self.can_touch()
            and self.game.board.squares[sq] != EMPTY
            and color_of(self.game.board.squares[sq]) == self.game.turn
        )
        hand = over_button or over_piece or self.drag
        cursor = pygame.SYSTEM_CURSOR_HAND if hand else pygame.SYSTEM_CURSOR_ARROW
        if cursor != self._cursor:
            self._cursor = cursor
            with contextlib.suppress(pygame.error):  # no mouse cursor in a headless test
                pygame.mouse.set_cursor(cursor)

    # -- The main loop --

    def run(self) -> None:
        clock = pygame.time.Clock()
        try:
            while self.running:
                for event in pygame.event.get():
                    self.handle(event)
                self.update()
                self.draw()
                pygame.display.flip()
                clock.tick(60)
        finally:
            self.close()

    def close(self) -> None:
        self._cancel_worker()
        self.analyst.close()
        pygame.quit()


LABEL_PLURAL = {
    "book": "Book moves",
    "best": "Best moves",
    "excellent": "Excellent",
    "good": "Good",
    "inaccuracy": "Inaccuracies",
    "mistake": "Mistakes",
    "miss": "Missed chances",
    "blunder": "Blunders",
}


BOARD_NAMES = [t.name for t in BOARD_THEMES]


def _next(options: list[str], current: str) -> str:
    """The option after ``current``, going round to the start."""
    return options[(options.index(current) + 1) % len(options)]


def play(opponent: str = "medium", human: str = WHITE, fen: str = START_FEN) -> None:
    App(opponent=opponent, human=human, fen=fen).run()
