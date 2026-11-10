"""python -m scraper run [--ran-by actions|mac] [--detail-limit N] [--force] [--push]"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, pipeline
from .http import Fetcher

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def push(day):
    git("add", "data/offers.json", "data/meta.json")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("Brak zmian w danych.")
        return
    git("commit", "-q", "-m", "Aktualizacja ofert %s" % day)
    git("pull", "-q", "--rebase")
    git("push", "-q")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scraper")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--ran-by", default="mac", choices=["actions", "mac"])
    parser.add_argument("--detail-limit", type=int, default=config.DETAIL_LIMIT)
    parser.add_argument("--force", action="store_true", help="uruchom mimo dzisiejszych danych")
    parser.add_argument("--push", action="store_true", help="commit i push data/*.json")
    args = parser.parse_args(argv)
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    code = pipeline.run(ROOT, Fetcher(), now, args.ran_by, args.detail_limit, args.force)
    if args.push:
        push(now.date().isoformat())
    return code


if __name__ == "__main__":
    sys.exit(main())
