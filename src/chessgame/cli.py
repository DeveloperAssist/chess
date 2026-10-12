"""The `chess` command.

chess                         open the game window (you play White against Medium)
chess --friend                two players on one screen
chess --black --level hard    play Black against Hard
chess terminal                play in the terminal instead of a window
chess perft 4                 count positions to check the move generator
"""

import argparse
import sys
import time

from .board import BLACK, START_FEN, WHITE, Board


def _game_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--friend", action="store_true", help="two players on one screen")
    parser.add_argument("--black", action="store_true", help="you play Black against the computer")
    parser.add_argument(
        "--level", choices=("easy", "medium", "hard"), default="medium", help="the computer's level"
    )
    parser.add_argument("--fen", default=START_FEN, help="start from this position (FEN)")
    parser.add_argument(
        "--seed", type=int, help="replay the computer's choices exactly (same seed, same game)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chess", description="Chess in Python, by Developers Assist.")
    commands = parser.add_subparsers(dest="command")
    _game_options(commands.add_parser("play", help="open the game window (the default)"))
    terminal = commands.add_parser("terminal", help="play in the terminal")
    _game_options(terminal)
    terminal.add_argument("--ascii", action="store_true", help="letters instead of chess symbols")
    perft = commands.add_parser("perft", help="count move sequences to test the rules")
    perft.add_argument("depth", type=int, help="how many moves deep, e.g. 4")
    perft.add_argument("--fen", default=START_FEN, help="start from this position (FEN)")
    perft.add_argument("--divide", action="store_true", help="also show the count for each first move")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["play", *argv]
    args = build_parser().parse_args(argv)

    if args.command == "perft":
        return _perft(args)

    try:
        Board(args.fen)
    except ValueError as error:
        print(f"That FEN doesn't work: {error}.", file=sys.stderr)
        return 2
    opponent = "friend" if args.friend else args.level
    human = BLACK if args.black else WHITE
    if args.command == "terminal":
        from .terminal import can_print_symbols, play_in_terminal

        symbols = can_print_symbols()
        if not symbols and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")  # print "?" rather than crash on "·" or "é"
        play_in_terminal(opponent, human, args.fen, ascii_only=args.ascii or not symbols, seed=args.seed)
    else:
        from .ui import play  # imported here, so `chess perft` and `chess terminal` don't need pygame

        play(opponent, human, args.fen, args.seed)
    return 0


def _perft(args: argparse.Namespace) -> int:
    from .perft import divide, perft

    board = Board(args.fen)
    print("perft from the start position" if args.fen == START_FEN else f"perft from {args.fen}")
    for depth in range(1, args.depth + 1):
        started = time.perf_counter()
        count = perft(board, depth)
        seconds = time.perf_counter() - started
        speed = f"   ({seconds:.2f} s, {count / seconds:,.0f} per second)" if seconds > 0.05 else ""
        print(f"  depth {depth}: {count:>12,}{speed}")
    if args.divide:
        print(f"\nBy first move (depth {args.depth}):")
        for move, count in sorted(divide(board, args.depth).items()):
            print(f"  {move}: {count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
