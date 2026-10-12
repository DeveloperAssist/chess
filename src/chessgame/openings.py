"""The opening book: famous openings, their names, and the idea behind each one.

Two kinds of data:

* ``NAMES`` name a position and explain the idea, e.g. the Italian Game after 1.e4 e5 2.Nf3 Nc6 3.Bc4.
* ``LINES`` are well-known move sequences the computer may play. The ``weight`` says how often:
  a line with weight 3 is picked three times as often as one with weight 1.

Positions are looked up by ``Board.position_key``, so a move order that transposes into a known
opening is still recognised.
"""

import random
from dataclasses import dataclass
from functools import cache

from .board import START_FEN, Board, Move
from .notation import parse_move


@dataclass(frozen=True, slots=True)
class Opening:
    name: str
    moves: str  # in SAN, e.g. "e4 e5 Nf3"
    idea: str = ""


NAMES = (
    # 1.e4 e5
    Opening("King's Pawn Opening", "e4", "Take the centre and open lines for your queen and bishop."),
    Opening("Open Game", "e4 e5", "Both sides take a share of the centre with their king's pawn."),
    Opening("King's Knight Opening", "e4 e5 Nf3", "Develop with a threat: the knight attacks e5."),
    Opening("Italian Game", "e4 e5 Nf3 Nc6 Bc4",
            "The bishop aims at f7, Black's weakest square, and White gets ready to castle."),
    Opening("Italian Game: Giuoco Piano", "e4 e5 Nf3 Nc6 Bc4 Bc5",
            "\"The quiet game\": Black copies White, and both bishops point at the enemy king."),
    Opening("Italian Game: Giuoco Pianissimo", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3",
            "A slow, solid plan: c3 and d3 first, then a long game of manoeuvres."),
    Opening("Italian Game: Evans Gambit", "e4 e5 Nf3 Nc6 Bc4 Bc5 b4",
            "White gives a pawn to win time for c3 and d4: a big centre and a fast attack."),
    Opening("Italian Game: Two Knights Defense", "e4 e5 Nf3 Nc6 Bc4 Nf6",
            "Black counterattacks e4 instead of copying White."),
    Opening("Italian Game: Two Knights Defense, Knight Attack", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5",
            "White attacks f7 at once with knight and bishop. Black must play ...d5."),
    Opening("Italian Game: Fried Liver Attack", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Nxd5 Nxf7",
            "A famous trap: White gives up a knight to drag Black's king into the open."),
    Opening("Ruy Lopez", "e4 e5 Nf3 Nc6 Bb5",
            "The bishop presses on the knight that guards e5. One of the oldest and most respected "
            "openings, also called the Spanish Game."),
    Opening("Ruy Lopez: Morphy Defense", "e4 e5 Nf3 Nc6 Bb5 a6",
            "Black asks the bishop what it wants, and keeps the option of ...b5 later."),
    Opening("Ruy Lopez: Closed", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O",
            "Both sides keep the centre closed and prepare for a long middlegame."),
    Opening("Ruy Lopez: Berlin Defense", "e4 e5 Nf3 Nc6 Bb5 Nf6",
            "A rock-solid defence, made famous in world championship matches."),
    Opening("Ruy Lopez: Exchange Variation", "e4 e5 Nf3 Nc6 Bb5 a6 Bxc6",
            "White gives the bishop for the knight to spoil Black's pawn structure."),
    Opening("Scotch Game", "e4 e5 Nf3 Nc6 d4",
            "White opens the centre straight away and gets free, active pieces."),
    Opening("Scotch Game: Classical Variation", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5"),
    Opening("Scotch Game: Schmidt Variation", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6"),
    Opening("Four Knights Game", "e4 e5 Nf3 Nc6 Nc3 Nf6",
            "Simple, healthy development: every knight goes to its best square."),
    Opening("Petrov's Defense", "e4 e5 Nf3 Nf6",
            "Black counterattacks e4 instead of defending e5. Very solid."),
    Opening("Philidor Defense", "e4 e5 Nf3 d6",
            "Black defends e5 with a pawn: solid, but it blocks the dark-squared bishop."),
    Opening("King's Gambit", "e4 e5 f4",
            "White gives a pawn to open the f-file and attack the king. Bold and risky."),
    Opening("King's Gambit Accepted", "e4 e5 f4 exf4"),
    Opening("King's Gambit Declined", "e4 e5 f4 Bc5"),
    Opening("Vienna Game", "e4 e5 Nc3",
            "The knight supports a later f4, a King's Gambit with more preparation."),
    Opening("Vienna Game: Vienna Gambit", "e4 e5 Nc3 Nf6 f4"),
    Opening("Bishop's Opening", "e4 e5 Bc4", "The bishop aims at f7 before the knights come out."),
    # 1.e4, other replies
    Opening("Sicilian Defense", "e4 c5",
            "Black fights for d4 from the side, for an unbalanced, fighting game. The most popular "
            "answer to 1.e4."),
    Opening("Sicilian Defense: Open", "e4 c5 Nf3 d6 d4 cxd4 Nxd4"),
    Opening("Sicilian Defense: Najdorf Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
            "...a6 keeps every option open. The favourite of Fischer and Kasparov."),
    Opening("Sicilian Defense: Dragon Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6",
            "The bishop on g7 breathes fire down the long diagonal."),
    Opening("Sicilian Defense: Classical Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 Nc6"),
    Opening("Sicilian Defense: Scheveningen Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6"),
    Opening("Sicilian Defense: Sveshnikov Variation", "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5"),
    Opening("Sicilian Defense: Taimanov Variation", "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6"),
    Opening("Sicilian Defense: Alapin Variation", "e4 c5 c3",
            "White prepares d4 with c3, to keep a full pawn centre."),
    Opening("Sicilian Defense: Closed", "e4 c5 Nc3 Nc6 g3"),
    Opening("Sicilian Defense: Smith-Morra Gambit", "e4 c5 d4 cxd4 c3",
            "White gives a pawn for fast development and open lines."),
    Opening("French Defense", "e4 e6",
            "Black builds a solid pawn chain and hits back later with ...c5."),
    Opening("French Defense: Advance Variation", "e4 e6 d4 d5 e5"),
    Opening("French Defense: Exchange Variation", "e4 e6 d4 d5 exd5 exd5"),
    Opening("French Defense: Winawer Variation", "e4 e6 d4 d5 Nc3 Bb4"),
    Opening("French Defense: Classical Variation", "e4 e6 d4 d5 Nc3 Nf6"),
    Opening("French Defense: Tarrasch Variation", "e4 e6 d4 d5 Nd2"),
    Opening("Caro-Kann Defense", "e4 c6",
            "Like the French, but the light-squared bishop gets out before ...e6. Very solid."),
    Opening("Caro-Kann Defense: Classical Variation", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5"),
    Opening("Caro-Kann Defense: Advance Variation", "e4 c6 d4 d5 e5"),
    Opening("Caro-Kann Defense: Exchange Variation", "e4 c6 d4 d5 exd5 cxd5"),
    Opening("Pirc Defense", "e4 d6 d4 Nf6 Nc3 g6",
            "Black lets White build a centre, planning to attack it later."),
    Opening("Modern Defense", "e4 g6", "Bishop to g7 first; the centre can wait."),
    Opening("Scandinavian Defense", "e4 d5",
            "Black challenges e4 at once. The queen comes out early, but to a safe square."),
    Opening("Scandinavian Defense: Modern Variation", "e4 d5 exd5 Nf6"),
    Opening("Alekhine's Defense", "e4 Nf6",
            "Black invites White's pawns forward, then attacks them."),
    # 1.d4
    Opening("Queen's Pawn Opening", "d4",
            "Take the centre with the pawn your queen already protects."),
    Opening("Queen's Gambit", "d4 d5 c4",
            "White offers a pawn to pull Black's d-pawn away from the centre."),
    Opening("Queen's Gambit Declined", "d4 d5 c4 e6",
            "Black keeps the pawn on d5 and develops solidly."),
    Opening("Queen's Gambit Accepted", "d4 d5 c4 dxc4",
            "Black takes the pawn, then gives it back for free, easy development."),
    Opening("Slav Defense", "d4 d5 c4 c6",
            "Black supports d5 with the c-pawn and keeps the light bishop free."),
    Opening("Semi-Slav Defense", "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6",
            "A Slav with ...e6 as well: rock-solid, with sharp lines where Black grabs c4."),
    Opening("London System", "d4 d5 Bf4",
            "A simple, reliable set-up: bishop to f4, then pawns on c3, d4 and e3. Great for "
            "beginners."),
    Opening("London System", "d4 Nf6 Bf4"),
    Opening("Indian Defense", "d4 Nf6", "Black controls e4 with a knight instead of a pawn."),
    Opening("King's Indian Defense", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",
            "Black lets White take the centre, then attacks it, often with ...e5 and ...f5."),
    Opening("Nimzo-Indian Defense", "d4 Nf6 c4 e6 Nc3 Bb4",
            "The pin on c3 stops e4. Black is happy to give the bishop for the knight."),
    Opening("Queen's Indian Defense", "d4 Nf6 c4 e6 Nf3 b6",
            "The bishop goes to b7 to watch e4 from far away."),
    Opening("Grünfeld Defense", "d4 Nf6 c4 g6 Nc3 d5",
            "Black lets White build a big centre, then attacks it with pieces."),
    Opening("Dutch Defense", "d4 f5",
            "Black grabs e4 with the f-pawn and aims for a king-side attack."),
    Opening("Benoni Defense", "d4 Nf6 c4 c5 d5",
            "An unbalanced fight: White has more space, Black has active pieces."),
    Opening("Catalan Opening", "d4 Nf6 c4 e6 g3",
            "A Queen's Gambit with the bishop on g2, pressing on the long diagonal."),
    Opening("Trompowsky Attack", "d4 Nf6 Bg5",
            "An early bishop move that knocks Black out of the books."),
    # Flank openings
    Opening("English Opening", "c4", "White fights for d5 from the side and keeps things flexible."),
    Opening("English Opening: Reversed Sicilian", "c4 e5"),
    Opening("English Opening: Symmetrical Variation", "c4 c5"),
    Opening("Réti Opening", "Nf3 d5 c4",
            "White controls the centre from a distance, with pieces instead of pawns."),
    Opening("King's Indian Attack", "Nf3 d5 g3",
            "A set-up you can play against almost anything: Nf3, g3, Bg2, castle, d3 and e4."),
    Opening("Zukertort Opening", "Nf3", "A flexible first move that keeps every plan open."),
    Opening("Bird's Opening", "f4", "White grabs e5 with the f-pawn: a Dutch Defense with an extra move."),
)  # fmt: skip

# (moves, weight): lines the computer plays. Popular, sound openings get bigger weights.
LINES = (
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O", 3),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4 cxd4 Bb4+ Bd2 Bxd2+ Nbxd2 d5", 1),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 b4 Bxb4 c3 Ba5 d4", 1),
    ("e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7 O-O O-O", 2),
    ("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Na5 Bb5+ c6", 1),
    ("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O", 3),
    ("e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4 d4 Nd6 Bxc6 dxc6 dxe5 Nf5 Qxd8+ Kxd8", 1),
    ("e4 e5 Nf3 Nc6 Bb5 a6 Bxc6 dxc6 O-O f6 d4 exd4 Nxd4 c5", 1),
    ("e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5 Be3 Qf6 c3 Nge7", 1),
    ("e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nxc6 bxc6 e5 Qe7 Qe2 Nd5 c4", 1),
    ("e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4 O-O O-O d3 d6", 1),
    ("e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3", 1),
    ("e4 e5 Nf3 d6 d4 Nf6 Nc3 Nbd7", 1),
    ("e4 e5 f4 exf4 Nf3 d5 exd5 Nf6", 1),
    ("e4 e5 f4 Bc5 Nf3 d6 c3 Nf6", 1),
    ("e4 e5 Nc3 Nf6 f4 d5 fxe5 Nxe4 Nf3", 1),
    ("e4 e5 Nc3 Nf6 Bc4 Nc6 d3 Bb4", 1),
    ("e4 e5 Bc4 Nf6 d3 c6 Nf3 d5 Bb3", 1),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6", 3),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6 Be3 Bg7 f3 O-O Qd2 Nc6", 2),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 Nc6 Bg5 e6", 1),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6 Be2 Be7 O-O O-O", 1),
    ("e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5 Ndb5 d6 Bg5 a6 Na3 b5", 1),
    ("e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6 Nc3 Qc7 Be3 a6", 1),
    ("e4 c5 c3 Nf6 e5 Nd5 d4 cxd4 Nf3 Nc6 cxd4 d6", 1),
    ("e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6", 1),
    ("e4 c5 d4 cxd4 c3 dxc3 Nxc3 Nc6 Nf3 d6 Bc4 e6 O-O Nf6", 1),
    ("e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6", 1),
    ("e4 e6 d4 d5 exd5 exd5 Bd3 Nc6 c3 Bd6", 1),
    ("e4 e6 d4 d5 Nc3 Bb4 e5 c5 a3 Bxc3+ bxc3 Ne7", 1),
    ("e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7 Bxe7 Qxe7", 1),
    ("e4 e6 d4 d5 Nd2 Nf6 e5 Nfd7 Bd3 c5 c3 Nc6", 1),
    ("e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6 Nf3 Nd7", 2),
    ("e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5", 1),
    ("e4 c6 d4 d5 exd5 cxd5 Bd3 Nc6 c3 Nf6 Bf4", 1),
    ("e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 c6", 1),
    ("e4 g6 d4 Bg7 Nc3 d6 Be3 a6", 1),
    ("e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6", 1),
    ("e4 d5 exd5 Nf6 d4 Nxd5 Nf3 g6", 1),
    ("e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4 Be2 e6", 1),
    ("d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 Nbd7", 3),
    ("d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6", 1),
    ("d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5 e3 e6", 2),
    ("d4 d5 c4 c6 Nf3 Nf6 Nc3 e6 e3 Nbd7 Bd3 dxc4 Bxc4 b5", 1),
    ("d4 d5 Bf4 Nf6 e3 e6 Nf3 c5 c3 Nc6 Nbd2 Bd6 Bg3 O-O", 2),
    ("d4 Nf6 Bf4 g6 e3 Bg7 Nf3 O-O Be2 d6 h3", 1),
    ("d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6 d5 Ne7", 2),
    ("d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5 Nf3 c5 O-O", 2),
    ("d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O Nc3 Ne4", 1),
    ("d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7 Nf3 c5", 1),
    ("d4 f5 g3 Nf6 Bg2 g6 Nf3 Bg7 O-O O-O c4 d6", 1),
    ("d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6 e4 g6 Nf3 Bg7", 1),
    ("d4 Nf6 c4 e6 g3 d5 Bg2 Be7 Nf3 O-O O-O dxc4 Qc2 a6", 1),
    ("d4 Nf6 Bg5 Ne4 Bf4 c5 f3 Qa5+ c3 Nf6", 1),
    ("c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5 Bg2 Nb6", 1),
    ("c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 Nf3 Nf6", 1),
    ("Nf3 d5 c4 e6 g3 Nf6 Bg2 Be7 O-O O-O", 1),
    ("Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 d3 O-O Nbd2 c5 e4", 1),
    ("f4 d5 Nf3 Nf6 e3 g6 b3 Bg7 Bb2", 1),
)


class OpeningBook:
    """Looks up positions: which book moves follow, and which opening this is."""

    def __init__(self, names=NAMES, lines=LINES) -> None:
        self.next: dict[str, dict[Move, int]] = {}  # position -> {book move: weight}
        self.openings: dict[str, Opening] = {}  # position -> the opening named there
        self.ideas: dict[str, str] = {}  # opening name -> its idea (the first one given)
        for opening in names:
            if opening.idea:
                self.ideas.setdefault(opening.name, opening.idea)
        for moves, weight in lines:
            self._walk(moves, weight)
        for opening in names:
            board = self._walk(opening.moves, 0)
            self.openings.setdefault(board.position_key(), opening)

    def _walk(self, moves: str, weight: int) -> Board:
        board = Board(START_FEN)
        for text in moves.split():
            move = parse_move(board, text)
            options = self.next.setdefault(board.position_key(), {})
            options[move] = options.get(move, 0) + weight
            board.make(move)
        return board

    def moves(self, board: Board) -> dict[Move, int]:
        """The book moves from this position, with their weights ({} when out of book)."""
        return self.next.get(board.position_key(), {})

    def is_book(self, board: Board, move: Move) -> bool:
        """Does this move reach a book position? (By any move order: transpositions count.)"""
        if move in self.moves(board):
            return True
        board.make(move)
        try:
            key = board.position_key()
        finally:
            board.unmake()
        return key in self.next or key in self.openings

    def choose(self, board: Board, rng: random.Random) -> Move | None:
        """A book move for the computer, picked at random by weight."""
        options = {m: w for m, w in self.moves(board).items() if w > 0}
        if not options:
            return None
        return rng.choices(list(options), weights=list(options.values()))[0]

    def best(self, board: Board) -> Move | None:
        """The most popular book move here (for the coach's suggestion)."""
        options = self.moves(board)
        return max(options, key=options.get) if options else None

    def name(self, fens: list[str]) -> Opening | None:
        """The opening of a game, from the most recent position that has a name."""
        for fen in reversed(fens):
            opening = self.openings.get(Board(fen).position_key())
            if opening:
                return opening
        return None

    def idea(self, opening: Opening) -> str:
        """The opening's idea, or its family's: 'Sicilian Defense: Najdorf Variation' falls back to
        'Sicilian Defense', and "King's Gambit Accepted" to "King's Gambit"."""
        if opening.idea:
            return opening.idea
        families = [name for name in self.ideas if opening.name.startswith(name)]
        return self.ideas[max(families, key=len)] if families else ""


@cache
def get_book() -> OpeningBook:
    """The opening book, built the first time it's needed (it takes a fraction of a second)."""
    return OpeningBook()


def book_move(board: Board, rng: random.Random) -> Move | None:
    return get_book().choose(board, rng)
