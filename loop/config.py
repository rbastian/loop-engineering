#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Read and check .loop/loop.toml, the local configuration of the loop.

loop.toml holds the facts that differ between machines: the paths, the agent
names, the engines and models, and the ship mode. This script is the one
reader of the file. Every subcommand checks the whole file first, prints every
error with its key path, and exits 1 if the file is not valid.

  config.py [--file PATH] check        exit 0 and print nothing if valid
  config.py [--file PATH] get T.KEY    print one value, defaults applied
  config.py [--file PATH] export       print KEY='value' lines for bash eval
  config.py [--file PATH] roles        print the Roles and paths prompt block

By default it reads loop.toml in its own directory. notify.py and reply.py
call load(), which returns the values with defaults applied, or raises
ConfigError with the list of error lines.
"""

import argparse
import sys
import tomllib
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "loop.toml"

REQUIRED = object()

# table -> key -> default (REQUIRED for a required key).
SCHEMA = {
    "project": {"primary": REQUIRED, "bead_prefix": REQUIRED, "human": REQUIRED},
    "ship": {"mode": REQUIRED, "github_account": ""},
    "coder": {"name": REQUIRED, "engine": "claude", "model": "", "worktree": REQUIRED},
    "reviewer": {
        "name": REQUIRED,
        "engine": "claude",
        "model": "",
        "worktree": REQUIRED,
    },
}

ALLOWED = {
    "ship.mode": ("pr", "local"),
    "coder.engine": ("claude", "fw"),
    "reviewer.engine": ("claude", "codex", "fw"),
}

PATHS = ("project.primary", "coder.worktree", "reviewer.worktree")

# The shell names that export and roles print, in order, with their key paths.
SHELL_NAMES = {
    "PRIMARY": "project.primary",
    "BEAD_PREFIX": "project.bead_prefix",
    "HUMAN": "project.human",
    "SHIP_MODE": "ship.mode",
    "GITHUB_ACCOUNT": "ship.github_account",
    "CODER": "coder.name",
    "CODER_ENGINE": "coder.engine",
    "CODER_MODEL": "coder.model",
    "CODER_WORKTREE": "coder.worktree",
    "REVIEWER": "reviewer.name",
    "REVIEWER_ENGINE": "reviewer.engine",
    "REVIEWER_MODEL": "reviewer.model",
    "REVIEWER_WORKTREE": "reviewer.worktree",
}


class ConfigError(Exception):
    """loop.toml is not valid. errors holds one line per problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def _one_of(values: tuple[str, ...]) -> str:
    return ", ".join(values[:-1]) + " or " + values[-1]


def _check_value(path: str, value: object) -> str | None:
    """The problem with one value on its own, or None."""
    if not isinstance(value, str):
        return f"must be a string (got: {value})"
    if "{{" in value:
        return f"contains a template placeholder (got: {value})"
    if path in ALLOWED and value not in ALLOWED[path]:
        return f"must be {_one_of(ALLOWED[path])} (got: {value})"
    if path in PATHS and not value.startswith("/"):
        return f"must be an absolute path (got: {value})"
    return None


def _validate(data: dict) -> tuple[dict, list[str]]:
    """Apply defaults and collect errors, without the file name prefix.

    The returned values hold only keys whose values passed their own checks.
    """
    errors = [f"{t}: unknown table" for t in data if t not in SCHEMA]
    values: dict[str, dict[str, str]] = {}
    for table, keys in SCHEMA.items():
        given = data.get(table, {})
        values[table] = {}
        if not isinstance(given, dict):
            errors.append(f"{table}: must be a table")
            continue
        errors += [f"{table}.{k}: unknown key" for k in given if k not in keys]
        for key, default in keys.items():
            path = f"{table}.{key}"
            if key not in given:
                if default is REQUIRED:
                    errors.append(f"{path}: missing required key")
                else:
                    values[table][key] = default
                continue
            problem = _check_value(path, given[key])
            if problem:
                errors.append(f"{path}: {problem}")
            else:
                values[table][key] = given[key]

    for role in ("coder", "reviewer"):
        if values[role].get("engine") == "fw" and values[role].get("model") == "":
            errors.append(f"{role}.model: must be set when engine is fw")

    mode = values["ship"].get("mode")
    account = values["ship"].get("github_account")
    if mode == "pr" and account == "":
        errors.append("ship.github_account: must be set in pr mode")
    elif mode == "local" and account:
        errors.append(
            f"ship.github_account: must be empty in local mode (got: {account})"
        )

    coder, reviewer = values["coder"].get("name"), values["reviewer"].get("name")
    if coder is not None and coder == reviewer:
        errors.append(f"reviewer.name: must differ from coder.name (got: {coder})")
    return values, errors


def load(path: Path | str = DEFAULT_FILE) -> dict:
    """Read and check loop.toml. Return the values with defaults applied."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except OSError as error:
        raise ConfigError(
            [f"{path.name}: cannot read the file ({error.strerror})"]
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError([f"{path.name}: {error}"]) from None
    values, errors = _validate(data)
    if errors:
        raise ConfigError([f"{path.name}: {e}" for e in errors])
    return values


def _get(values: dict, path: str) -> str:
    table, key = path.split(".")
    return values[table][key]


def _shell_lines(values: dict, quote: bool) -> list[str]:
    lines = []
    for name, path in SHELL_NAMES.items():
        value = _get(values, path)
        if quote:
            value = "'" + value.replace("'", "'\\''") + "'"
        lines.append(f"{name}={value}")
    return lines


def main(argv: list[str] | None = None) -> int:
    # --file works before or after the subcommand. The subcommand's copy
    # defaults to SUPPRESS, so that it does not hide the top-level value.
    sub_file = argparse.ArgumentParser(add_help=False)
    sub_file.add_argument("--file", type=Path, default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(description="Read and check loop.toml.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", parents=[sub_file], help="check the file")
    get = commands.add_parser("get", parents=[sub_file], help="print one value")
    get.add_argument("key", help="table.key, for example coder.model")
    commands.add_parser("export", parents=[sub_file], help="print shell lines")
    commands.add_parser("roles", parents=[sub_file], help="print the prompt block")
    args = parser.parse_args(argv)

    try:
        values = load(args.file)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1

    if args.command == "get":
        table, _, key = args.key.partition(".")
        if key not in SCHEMA.get(table, {}):
            print(f"{args.file.name}: {args.key}: unknown key", file=sys.stderr)
            return 1
        print(_get(values, args.key))
    elif args.command == "export":
        print("\n".join(_shell_lines(values, quote=True)))
    elif args.command == "roles":
        lines = _shell_lines(values, quote=False)
        print("\n".join(["## Roles and paths", "", "```bash", *lines, "```"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
