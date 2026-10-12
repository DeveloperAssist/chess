import threading
import time

import pytest

from chessgame.ai import MATE
from chessgame.analysis import (
    ANALYSIS,
    REPLY,
    AnalysisCache,
    Analyst,
    analyse,
    expected,
    format_score,
    grade,
    jobs_for,
    mate_in,
    move_accuracy,
    review_game,
    summarise,
    white_expected,
)
from chessgame.board import BLACK, WHITE, Board, Move
from chessgame.game import Game


def game_after(moves: str, fen: str | None = None) -> Game:
    game = Game(fen) if fen else Game()
    for move in moves.split():
        game.play(move)
    return game


def test_expected_result_from_a_score():
    assert expected(0) == pytest.approx(0.5)
    assert expected(300) == pytest.approx(0.75, abs=0.01)
    assert expected(-300) == pytest.approx(0.25, abs=0.01)
    assert expected(MATE - 3) == 1.0 and expected(-(MATE - 3)) == 0.0
    assert expected(900) < expected(1200) < 1.0


def test_mate_in_and_score_text():
    assert mate_in(MATE - 1) == 1
    assert mate_in(MATE - 3) == 2
    assert mate_in(-(MATE - 2)) == -1
    assert mate_in(250) is None
    assert format_score(123) == "+1.2"
    assert format_score(-40) == "-0.4"
    assert format_score(MATE - 5) == "M3"
    assert format_score(-(MATE - 1)) == "-M1"


@pytest.mark.parametrize(
    ("best", "played", "kind"),
    [
        (30, 30, "best"),
        (30, 20, "excellent"),
        (30, -5, "good"),
        (30, -50, "inaccuracy"),
        (30, -150, "mistake"),
        (30, -400, "blunder"),
        (MATE - 1, 500, "miss"),  # mate in one, but played something merely winning
        (400, 100, "miss"),  # a big advantage mostly thrown away, but not lost
        (400, -300, "blunder"),  # from winning to losing is a blunder, not a miss
    ],
)
def test_grades(best, played, kind):
    assert grade(best, played, is_best=False, is_book=False)[0] == kind


def test_book_and_best_moves_are_never_mistakes():
    assert grade(30, -400, is_best=False, is_book=True) == ("book", 0.0)
    assert grade(30, -400, is_best=True, is_book=False)[0] == "best"


def test_accuracy_falls_with_the_loss():
    assert move_accuracy(0) == pytest.approx(100, abs=0.1)
    assert 50 < move_accuracy(0.1) < move_accuracy(0.05) < 100
    assert move_accuracy(1.0) == 0


def test_analyse_finished_and_dead_positions():
    mate = analyse(Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"))
    assert mate.best is None and mate.score == -MATE
    dead = analyse(Board("8/8/8/4k3/8/8/8/3BK3 w - - 0 1"))
    assert dead.score == 0


def test_scholars_mate_review():
    reviews = review_game(game_after("e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7"))
    kinds = [r.kind for r in reviews]
    assert kinds[:2] == ["book", "book"]
    nf6 = reviews[5]
    assert nf6.kind == "blunder" and nf6.reply_san == "Qxf7#"
    assert reviews[6].kind == "best" and reviews[6].san == "Qxf7#"
    black = summarise(reviews, BLACK)
    assert black.counts["blunder"] == 1 and black.moves == 3
    assert "1 blunder" in black.line()
    assert summarise(reviews, WHITE).accuracy > black.accuracy


def test_a_hanging_queen_is_a_blunder():
    reviews = review_game(game_after("e4 e5 Nf3 Qh4 Nxh4"))
    assert reviews[3].kind == "blunder" and reviews[3].reply_san == "Nxh4"
    assert reviews[4].kind == "best"


def test_missing_a_mate_in_one_is_a_missed_chance():
    game = game_after("h3", fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")  # Ra8# was mate
    (review,) = review_game(game)
    assert review.kind == "miss" and review.best_san == "Ra8#"


def test_jobs_put_the_current_position_first():
    game = game_after("e4 e5 Nf3")
    jobs = jobs_for(game)
    assert jobs[0] == (game.fens[-1], ANALYSIS)
    assert jobs[1:3] == [(game.fens[2], ANALYSIS), (game.fens[3], REPLY)]
    assert len(jobs) == 1 + 2 * 3


def test_cache_does_the_work_once():
    cache = AnalysisCache()
    fen = Game().fens[0]
    assert cache.get(fen) is None
    first = cache.compute(fen)
    started = time.perf_counter()
    assert cache.compute(fen) is first
    assert time.perf_counter() - started < 0.01
    assert white_expected(fen, cache) == pytest.approx(0.5, abs=0.15)


def test_analyst_thread_works_in_the_background_and_waits_while_paused():
    analyst = Analyst(threaded=True)
    try:
        analyst.allowed.clear()  # as if the computer were thinking
        game = game_after("d4 d5")
        analyst.want(jobs_for(game))
        time.sleep(0.3)
        assert analyst.cache.get(game.fens[-1]) is None
        analyst.allowed.set()
        deadline = time.perf_counter() + 30
        while analyst.pending() and time.perf_counter() < deadline:
            time.sleep(0.02)
        assert analyst.pending() == 0
        assert analyst.version >= 5
    finally:
        analyst.close()


def test_a_stopped_analysis_is_not_kept():
    cache = AnalysisCache()
    stop = threading.Event()
    stop.set()
    cache.compute("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", stop=stop)
    assert cache.get("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1") is None


def test_review_move_numbers_and_colours():
    reviews = review_game(game_after("Nf3", fen="4k3/8/8/8/8/8/8/4K1N1 w - - 0 1"))
    assert reviews[0].color == WHITE and reviews[0].move == Move.from_uci("g1f3")
