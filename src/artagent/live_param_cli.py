"""Inspect or adjust one explicit ART GUI editor through its local socket."""

import argparse
import json
import sys

from .live_param import Client, LiveParamError, Target, _duration


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--timeout", type=float, default=3.0)
    commands = parser.add_subparsers(dest="command", required=True)
    state = commands.add_parser("state", help="List editors or inspect an explicit editor")
    state.add_argument("--session")
    state.add_argument("--editor")
    mutation = commands.add_parser("set", help="Set absolute Exposure.Compensation in EV")
    mutation.add_argument("--session", required=True)
    mutation.add_argument("--editor", required=True)
    mutation.add_argument("--revision", required=True, type=int)
    mutation.add_argument("--value", required=True, type=float)
    mutation.add_argument("--request-id")
    mutation.add_argument("--wait", action="store_true")
    mutation.add_argument("--wait-timeout", type=float, default=30.0)
    status = commands.add_parser("status", help="Inspect the original mutation without resending")
    status.add_argument("--session", required=True)
    status.add_argument("--editor", required=True)
    status.add_argument("--mutation", required=True)
    args = parser.parse_args(argv)
    try:
        client = Client(args.socket, timeout=args.timeout)
        target = None
        if args.editor or args.session:
            target = Target(args.session, args.editor, getattr(args, "revision", 0))
        if args.command == "set":
            _duration(args.wait_timeout)  # Validate before any possible mutation.
            if not -12 <= args.value <= 12:
                raise ValueError("Exposure must be a finite number in [-12,12]")
            response = client.set_exposure(target, args.value, request_id=args.request_id)
            if args.wait:
                prepared = client.wait_ready(target, response, timeout=args.wait_timeout)
                response = {"status": "READY", "applied": response, "state": prepared}
        else:
            response = client.get_state(target, mutation_request_id=getattr(args, "mutation", None))
    except ValueError as error:
        parser.error(str(error))
    except LiveParamError as error:
        partial = error.applied is not None or error.uncertain
        response = {
            "status": "PARTIAL" if partial else "ERROR",
            "error": {"code": error.code, "message": str(error), "requestId": error.request_id},
        }
        if error.applied is not None:
            response["applied"] = error.applied
        print(json.dumps(response, ensure_ascii=False, allow_nan=False))
        return 3 if partial else 1
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
