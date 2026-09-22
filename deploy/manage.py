#!/usr/bin/env python3
"""Operate the server from a workstation or GitHub Actions, over verified SSH."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deploy.controller import IMAGE, validate_settings


REMOTE = """
import json, sys
request = json.load(sys.stdin)
scope = {'__name__': 'deployment_controller'}
try:
    exec(compile(request['controller'], '<deployment-controller>', 'exec'), scope)
    scope['handle'](request)
except Exception as exc:
    print('[ERR] ' + str(exc), file=sys.stderr)
    sys.exit(1)
"""


def ssh_command(settings: dict) -> list[str]:
    if set(settings) - {"host", "port", "identity_file", "known_hosts"}:
        raise ValueError("unknown SSH setting")
    host = settings.get("host", "")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
        raise ValueError("ssh.host must be an SSH alias or user@hostname")
    port = settings.get("port", 22)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid SSH port")
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-p", str(port)]
    if settings.get("identity_file"):
        args += ["-o", "IdentitiesOnly=yes", "-i", str(Path(settings["identity_file"]).expanduser())]
    if settings.get("known_hosts"):
        args += ["-o", "UserKnownHostsFile=" + str(Path(settings["known_hosts"]).expanduser())]
    return args + [host, "python3 -u -c " + shlex.quote(REMOTE)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--identity-file", type=Path, help="Override the SSH key (e.g. in CI)")
    parser.add_argument("--known-hosts", type=Path, help="Override the verified SSH host-key file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print plan without SSH")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("deploy").add_argument("--image", required=True)
    commands.add_parser("rollback").add_argument("--release", help="Default: previous release")
    for action in ("run", "preview", "doctor", "status"):
        commands.add_parser(action)
    args = parser.parse_args(argv)
    try:
        with args.target.open("rb") as source:
            target = tomllib.load(source)
        if set(target) != {"ssh", "deployment"}:
            raise ValueError("target must contain [ssh] and [deployment] only")
        settings = target["deployment"]
        for field in ("identity_file", "known_hosts"):
            if getattr(args, field):
                target["ssh"][field] = str(getattr(args, field))
        settings.setdefault("download_timeout", 900)
        validate_settings(settings)
        if args.action == "deploy" and not IMAGE.fullmatch(args.image):
            raise ValueError("--image must use ghcr.io/...@sha256:<64 hex digits>")
        directory = Path(__file__).resolve().parent
        request = dict(action=args.action, settings=settings,
                       controller=(directory / "controller.py").read_text())
        if args.action == "deploy":
            request.update(image=args.image, compose=json.loads((directory / "compose.json").read_text()))
        if args.action == "rollback":
            request["release"] = args.release
        command = ssh_command(target["ssh"])
        if args.dry_run:
            print(json.dumps({k: v for k, v in request.items() if k not in {"controller", "compose"}}, indent=2))
            print(f'SSH target: {target["ssh"]["host"]}; host key verification required')
            return 0
        return subprocess.run(command, input=json.dumps(request), text=True, check=False).returncode
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
