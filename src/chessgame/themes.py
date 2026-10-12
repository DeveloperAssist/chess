"""Looks: board colours, piece sets, fonts, and the settings file that remembers your choice.

Every piece set is drawn from the chess symbols in a font (no image files), in different styles:
plain, wood and gold gradients, glowing neon, or letters for learning the notation.
"""

import contextlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

RGB = tuple[int, int, int]

# The Developers Assist dark theme, for everything around the board.
BG = (10, 14, 19)
PANEL = (15, 20, 27)
CARD = (20, 27, 36)
LINE = (28, 36, 48)
TEXT = (232, 237, 243)
MUTED = (139, 151, 166)
CYAN = (34, 195, 230)
GREEN = (74, 222, 128)
AMBER = (251, 191, 36)
RED = (239, 68, 68)

# One colour per kind of move, used in the move list, the review and the arrows.
KIND_COLOURS = {
    "book": (196, 160, 110),
    "best": (74, 222, 128),
    "excellent": (134, 239, 172),
    "good": (148, 163, 184),
    "inaccuracy": (250, 204, 21),
    "mistake": (249, 115, 22),
    "miss": (192, 132, 252),
    "blunder": (239, 68, 68),
}


@dataclass(frozen=True, slots=True)
class BoardTheme:
    name: str
    light: RGB
    dark: RGB
    highlight: RGB  # the last move and the selected piece are tinted with this


BOARD_THEMES = (
    BoardTheme("Slate", (222, 228, 235), (122, 146, 170), (34, 195, 230)),
    BoardTheme("Wood", (240, 217, 181), (181, 136, 99), (214, 214, 70)),
    BoardTheme("Green", (235, 236, 208), (115, 149, 82), (246, 246, 105)),
    BoardTheme("Ocean", (214, 230, 242), (70, 120, 170), (120, 220, 255)),
    BoardTheme("Rose", (246, 228, 232), (190, 110, 130), (255, 214, 102)),
    BoardTheme("Midnight", (86, 98, 116), (44, 52, 66), (34, 195, 230)),
)
PIECE_SETS = ("Classic", "Wood", "Royal", "Neon", "Letters")


def board_theme(name: str) -> BoardTheme:
    return next((t for t in BOARD_THEMES if t.name == name), BOARD_THEMES[0])


# --- Settings ----------------------------------------------------------------------------------

SETTINGS_FILE = Path.home() / ".chess-in-python.json"


@dataclass
class Settings:
    board: str = "Slate"
    pieces: str = "Classic"
    coach: bool = True  # evaluation bar and a grade for every move while you play

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        settings = cls()
        if not isinstance(data, dict):
            return settings
        if data.get("board") in {t.name for t in BOARD_THEMES}:
            settings.board = data["board"]
        if data.get("pieces") in PIECE_SETS:
            settings.pieces = data["pieces"]
        if isinstance(data.get("coach"), bool):
            settings.coach = data["coach"]
        return settings

    def save(self, path: Path) -> None:
        with contextlib.suppress(OSError):  # a read-only home folder shouldn't stop the game
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# --- Fonts -------------------------------------------------------------------------------------

SOLID_GLYPHS = dict(zip("kqrbnp", "\u265a\u265b\u265c\u265d\u265e\u265f", strict=True))
LINE_GLYPHS = dict(zip("kqrbnp", "\u2654\u2655\u2656\u2657\u2658\u2659", strict=True))
WINDOWS_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def font_file(files: list[str], names: list[str], bold: bool = False) -> str | None:
    """The first font we can find: Windows font files first, then installed fonts by name."""
    for name in files:
        if (WINDOWS_FONTS / name).exists():
            return str(WINDOWS_FONTS / name)
    for name in names:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return path
    return None  # pygame's own built-in font


def find_piece_font() -> str | None:
    """A font that has the chess symbols (U+2654 to U+265F), or None."""
    candidates = [str(WINDOWS_FONTS / "seguisym.ttf")] + [
        pygame.font.match_font(name)
        for name in ("segoeuisymbol", "dejavusans", "notosanssymbols2", "applesymbols",
                     "arialunicodems", "freeserif", "symbola")
    ]  # fmt: skip
    glyphs = "".join(SOLID_GLYPHS.values()) + "".join(LINE_GLYPHS.values())
    for path in candidates:
        if path and os.path.exists(path):
            metrics = pygame.font.Font(path, 32).metrics(glyphs)
            if all(metrics):
                return path
    return None


def strong_font_file() -> str | None:
    return font_file(["seguisb.ttf", "segoeuib.ttf"], ["intersemibold", "dejavusans"], True)


class Fonts:
    def __init__(self, s: int) -> None:
        regular = font_file(["segoeui.ttf"], ["inter", "dejavusans", "helveticaneue", "arial"])
        strong = strong_font_file()
        mono = font_file(["consola.ttf"], ["jetbrainsmono", "dejavusansmono", "menlo", "couriernew"])
        self.title = pygame.font.Font(strong, round(s * 0.34))
        self.banner = pygame.font.Font(strong, round(s * 0.42))
        self.strong = pygame.font.Font(strong, round(s * 0.19))
        self.body = pygame.font.Font(regular, round(s * 0.19))
        self.small_strong = pygame.font.Font(strong, round(s * 0.165))
        self.small = pygame.font.Font(regular, round(s * 0.165))
        self.tiny = pygame.font.Font(strong, round(s * 0.14))
        self.coord = pygame.font.Font(strong, round(s * 0.15))
        self.mono = pygame.font.Font(mono, round(s * 0.18))


# --- Pieces ------------------------------------------------------------------------------------

# Colours per piece set: (fill top, fill bottom, line) for White, then for Black. Classic has
# no gradient: its top and bottom colours are the same.
FILLS = {
    "Classic": (((250, 251, 252), (250, 251, 252), (22, 28, 36)),
                ((30, 36, 45), (30, 36, 45), (230, 234, 240))),
    "Wood": (((250, 232, 200), (214, 170, 112), (74, 46, 24)),
             ((132, 88, 56), (62, 38, 22), (246, 226, 196))),
    "Royal": (((255, 238, 170), (214, 162, 46), (84, 58, 12)),
              ((78, 98, 170), (26, 34, 74), (244, 206, 96))),
}  # fmt: skip
NEON = {True: (34, 211, 238), False: (244, 114, 182)}


class PieceArt:
    """Draws the 12 pieces once, at one size and in one style, and keeps the pictures.

    * Classic: a white piece is the solid symbol filled white, with the outline symbol drawn over
      it in a dark colour. A black piece is the solid symbol in a dark colour with a thin light
      edge, so it stands out on dark squares.
    * Wood and Royal: the same, with a top-to-bottom colour gradient instead of a flat colour.
    * Neon: a dark body with a glowing coloured outline (cyan for White, pink for Black).
    * Letters: K, Q, R, B, N, P in circles: handy while you learn the notation.

    With no chess font installed, every style falls back to Letters."""

    def __init__(self, size: int, font_path: str | None, style: str = "Classic",
                 letter_font: str | None = None) -> None:  # fmt: skip
        self.size = size
        self.style = style if font_path else "Letters"
        self.font = pygame.font.Font(font_path, round(size * 0.86)) if font_path else None
        self.letter_font = pygame.font.Font(letter_font, round(size * 0.5))
        self.images = {p: self._draw(p) for p in "KQRBNPkqrbnp"}

    def __getitem__(self, piece: str) -> pygame.Surface:
        return self.images[piece]

    def _draw(self, piece: str) -> pygame.Surface:
        image = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
        kind, white = piece.lower(), piece.isupper()
        if self.style == "Letters":
            self._letters(image, kind, white)
        elif self.style == "Neon":
            self._neon(image, kind, white)
        else:
            self._glyphs(image, kind, white)
        return image

    def _blit_centred(self, image: pygame.Surface, surface: pygame.Surface, shift=(0, 0)) -> None:
        box = surface.get_bounding_rect()
        centre = pygame.Vector2(self.size / 2, self.size / 2)
        image.blit(surface, centre - pygame.Vector2(box.center) + pygame.Vector2(shift))

    def _render(self, glyph: str, colour) -> pygame.Surface:
        return self.font.render(glyph, True, colour)

    def _fill(self, glyph: str, top: RGB, bottom: RGB) -> pygame.Surface:
        """The glyph filled with a vertical gradient (a flat colour when top == bottom)."""
        mask = self._render(glyph, (255, 255, 255))
        if top == bottom:
            return self._render(glyph, top)
        width, height = mask.get_size()
        box = mask.get_bounding_rect()
        gradient = pygame.Surface((width, height), pygame.SRCALPHA)
        for y in range(height):
            t = min(1.0, max(0.0, (y - box.top) / max(1, box.height - 1)))
            colour = [round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)]
            pygame.draw.line(gradient, (*colour, 255), (0, y), (width, y))
        gradient.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        return gradient

    def _shadow(self, image: pygame.Surface, kind: str) -> None:
        shadow = self._render(SOLID_GLYPHS[kind], (0, 0, 0))
        shadow.set_alpha(70)
        self._blit_centred(image, shadow, (0, self.size * 0.035))

    def _edge(self, image: pygame.Surface, kind: str, colour: RGB) -> None:
        """A thin outline: the solid symbol drawn in ``colour`` a pixel or two off in 8 directions."""
        edge = self._render(SOLID_GLYPHS[kind], colour)
        w = max(1.0, self.size * 0.019)
        for dx, dy in ((-w, 0), (w, 0), (0, -w), (0, w)):
            self._blit_centred(image, edge, (dx, dy))
        for dx, dy in ((-1, -1), (1, 1), (-1, 1), (1, -1)):
            self._blit_centred(image, edge, (dx * w * 0.7, dy * w * 0.7))

    def _glyphs(self, image: pygame.Surface, kind: str, white: bool) -> None:
        top, bottom, line = FILLS.get(self.style, FILLS["Classic"])[0 if white else 1]
        self._shadow(image, kind)
        if not white:
            self._edge(image, kind, line)
        self._blit_centred(image, self._fill(SOLID_GLYPHS[kind], top, bottom))
        if white:
            self._blit_centred(image, self._render(LINE_GLYPHS[kind], line))

    def _neon(self, image: pygame.Surface, kind: str, white: bool) -> None:
        colour = NEON[white]
        outline = self._render(LINE_GLYPHS[kind], colour)
        width, height = outline.get_size()
        small = pygame.transform.smoothscale(outline, (max(1, width // 5), max(1, height // 5)))
        glow = pygame.transform.smoothscale(small, (width, height))
        for _ in range(3):
            self._blit_centred(image, glow)
        self._blit_centred(image, self._render(SOLID_GLYPHS[kind], (14, 18, 26)))
        self._blit_centred(image, outline)

    def _letters(self, image: pygame.Surface, kind: str, white: bool) -> None:
        size = self.size
        fill, line = ((245, 247, 250), (30, 36, 45)) if white else ((30, 36, 45), (230, 234, 240))
        centre = (size / 2, size / 2)
        pygame.draw.circle(image, (0, 0, 0, 60), (size / 2, size / 2 + size * 0.035), size * 0.38)
        pygame.draw.circle(image, fill, centre, size * 0.38)
        pygame.draw.circle(image, line, centre, size * 0.38, max(1, size // 24))
        letter = self.letter_font.render(kind.upper(), True, line)
        image.blit(letter, letter.get_rect(center=centre))
