from chessgame.progress import KEEP, GameRecord, fingerprint, load_history, record_game


def record(game_id: str, accuracy: float = 80.0) -> GameRecord:
    return GameRecord(game_id, "2026-10-12", "medium", "win", accuracy, 0, 1, 0)


def test_games_are_recorded_once_and_in_order(tmp_path):
    path = tmp_path / "history.json"
    record_game(path, record("a", 70))
    record_game(path, record("b", 75))
    record_game(path, record("a", 99))  # the same game again: ignored
    assert [(g.game_id, g.accuracy) for g in load_history(path)] == [("a", 70), ("b", 75)]


def test_only_the_latest_games_are_kept(tmp_path):
    path = tmp_path / "history.json"
    for i in range(KEEP + 5):
        record_game(path, record(str(i)))
    games = load_history(path)
    assert len(games) == KEEP and games[0].game_id == "5"


def test_a_broken_history_file_starts_fresh(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{oops", encoding="utf-8")
    assert load_history(path) == []
    path.write_text('[{"wrong": 1}]', encoding="utf-8")
    assert load_history(path) == []


def test_fingerprints_tell_games_apart():
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert fingerprint(start, ["e2e4"]) == fingerprint(start, ["e2e4"])
    assert fingerprint(start, ["e2e4"]) != fingerprint(start, ["d2d4"])
