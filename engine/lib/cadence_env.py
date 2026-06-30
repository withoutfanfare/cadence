"""Shared .env loader for the Cadence python adapters. Stdlib only."""
import os


def _parse_value(val):
    """Mirror how bash sources the same line: a quoted value keeps its contents
    verbatim; an unquoted value ends at the first whitespace, so an inline
    `# comment` after the value is dropped (a `#` with no leading space is kept)."""
    val = val.lstrip()
    if not val or val[0] == "#":
        return ""
    if val[0] in ("'", '"'):
        q = val[0]
        end = val.find(q, 1)
        return val[1:end] if end != -1 else val[1:].strip()
    return val.split()[0]


def load_env(home=None):
    home = home or os.environ.get("CADENCE_HOME") or os.getcwd()
    env = {}
    path = os.path.join(home, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                env[key.strip()] = _parse_value(val)
    # Real environment wins over the file (lets callers/tests inject).
    env.update(os.environ)
    return env
