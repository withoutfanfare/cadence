"""Shared worktree helpers for engine adapters. Stdlib only."""

import os
import subprocess
import sys


def remove_worktree(branch, env=None):
    env = env or os.environ
    if not branch or not env.get("PROJECT_DIR") or not env.get("WORKTREE_BASE"):
        return False
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "worktree.sh")
    run_env = os.environ.copy()
    run_env.update(env)
    result = subprocess.run(
        ["bash", script, "remove", branch],
        env=run_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or f"worktree cleanup failed for {branch}\n")
        return False
    return True
