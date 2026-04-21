"""Allow `python -m nanobot.dashboard` as an alias for the server."""

from nanobot.dashboard.server import _parse_args, run

if __name__ == "__main__":
    args = _parse_args()
    run(host=args.host, port=args.port)
