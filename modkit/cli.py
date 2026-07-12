"""modkit CLI dispatch. Run: py -3 C:\\Modding\\tools\\modkit.py <cmd> --game skyrim

Exit codes: 0 clean/success, 1 error or verify findings, 2 warned (forceable gate).
"""
import argparse
import sys

from modkit import config


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "backslashreplace").decode("ascii"))


def _preset(args):
    cfg = config.load(getattr(args, "config", None))
    game = getattr(args, "game", None)
    if not game:
        raise config.ConfigError("missing --game (e.g. --game skyrim)")
    return config.game(cfg, game)


def _add_globals(parser):
    # SUPPRESS: unprovided flags set no attribute, so subparser parsing never
    # clobbers a value parsed before the subcommand (ledger.py precedent).
    parser.add_argument("--game", default=argparse.SUPPRESS,
                        help="game preset from modkit.json (skyrim | cp77 | ...)")
    parser.add_argument("--config", default=argparse.SUPPRESS,
                        help="explicit modkit.json path (default: MODKIT_CONFIG env, then repo file)")


def build_parser():
    p = argparse.ArgumentParser(prog="modkit.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_globals(p)
    common = argparse.ArgumentParser(add_help=False)
    _add_globals(common)
    sub = p.add_subparsers(dest="command", required=True)
    _register_all(sub, common)
    return p


def _register_all(sub, common):
    """Each task appends its register_<cmd>(sub, common) call here."""


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as ex:
        safe_print(f"ERROR: {ex}")
        return 1
