"""Your learning curve: a small file that remembers how accurately you played each game against
the computer, so you can see yourself improve."""

import contextlib
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

HISTORY_FILE = Path.home() / ".chess-in-python-history.json"
KEEP = 200  # games remembered


@dataclass(frozen=True, slots=True)
class GameRecord:
    game_id: str  # a fingerprint of the moves, so the same game is never counted twice
    day: str
    level: str
    result: str  # "win", "loss" or "draw", for you
    accuracy: float
    blunders: int
    mistakes: int
    misses: int


def fingerprint(start_fen: str, ucis: list[str]) -> str:
    return hashlib.sha1((start_fen + " " + " ".join(ucis)).encode()).hexdigest()[:16]


def load_history(path: Path) -> list[GameRecord]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [GameRecord(**entry) for entry in data]
    except (OSError, ValueError, TypeError):
        return []


def record_game(path: Path, record: GameRecord) -> list[GameRecord]:
    """Add a game (once) and return the whole history, oldest first."""
    history = load_history(path)
    if all(r.game_id != record.game_id for r in history):
        history = [*history, record][-KEEP:]
        with contextlib.suppress(OSError):
            path.write_text(json.dumps([asdict(r) for r in history], indent=1), encoding="utf-8")
    return history


def today() -> str:
    return date.today().isoformat()
