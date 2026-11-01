"""``python -m eka [--host H] [--port P] [--reload]``"""

import argparse

from eka.runtime import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="eka", description="Run the EKA API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    run(args.host, args.port, reload=args.reload)


if __name__ == "__main__":
    main()
