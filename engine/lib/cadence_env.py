"""Shared .env loader for the Cadence python adapters. Stdlib only."""
import os
import sys


def _warn(key, msg):
    sys.stderr.write(f"cadence env: {key or '?'}: {msg}\n")


def _parse_value(val, key=None):
    """Mirror how bash sources the same line: a quoted value keeps its contents
    verbatim; an unquoted value ends at the first whitespace, so an inline
    `# comment` after the value is dropped (a `#` with no leading space is kept).

    This does not reimplement bash's `\\"` escaping — it warns instead, because a
    silent divergence would change what an unquoted-looking gate command runs."""
    val = val.lstrip()
    if not val or val[0] == "#":
        return ""
    if val[0] in ("'", '"'):
        q = val[0]
        end = val.find(q, 1)
        if end == -1:
            _warn(key, "unterminated quote — value taken to end of line")
            return val[1:].strip()
        if q == '"' and end > 1 and val[end - 1] == "\\":
            _warn(key, "value contains a backslash-escaped quote; this parser "
                       "stops at it — use the other quote style instead")
        return val[1:end]
    return val.split()[0]


def resolve_env_path(home=None, cwd=None):
    home = home or os.environ.get("CADENCE_HOME") or os.getcwd()
    explicit = os.environ.get("CADENCE_CONFIG")
    if explicit:
        return explicit
    project_env = os.path.join(cwd or os.getcwd(), "cadence", ".env")
    if os.path.exists(project_env):
        return project_env
    return os.path.join(home, ".env")


def load_env(home=None, cwd=None):
    env = {}
    path = resolve_env_path(home=home, cwd=cwd)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                env[key] = _parse_value(val, key)
    # Real environment wins over the file (lets callers/tests inject).
    env.update(os.environ)
    env["CADENCE_CONFIG"] = path
    return env
