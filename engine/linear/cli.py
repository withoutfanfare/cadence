"""Cadence Linear adapter — speaks the Linear GraphQL API. Stdlib only.

Replaces the Linear MCP. Reads ids/key from .env (via cadence_env). Each cmd_*
is `cmd_x(args, env, post=graphql)`; pass a fake post in tests. main() prints
the result as JSON.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cadence_env import load_env  # noqa: E402
from stages import dep_mode, dep_satisfied, resolve_labels, strip_workflow_labels  # noqa: E402
from stages import stage_of  # noqa: E402
from worktrees import remove_worktree as _remove_worktree  # noqa: E402

API_URL = "https://api.linear.app/graphql"


class LinearError(RuntimeError):
    pass


def _require_env(env, *names):
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise LinearError(f"missing required env value(s): {', '.join(missing)}")


# Transient HTTP statuses worth a retry; anything else fails fast.
_RETRY_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
# Cap any single backoff so a hostile/huge Retry-After can't block a scheduled slot
# longer than the next tick would take to come round anyway.
_MAX_RETRY_DELAY = 60


def _retry_delay(headers, attempt):
    """Seconds to wait before the next attempt: honour a numeric Retry-After
    header when present, else exponential backoff (2 ** attempt). Capped."""
    if headers is not None:
        raw = headers.get("Retry-After")
        if raw:
            try:
                return max(0, min(int(raw), _MAX_RETRY_DELAY))
            except (TypeError, ValueError):
                pass
    return min(2 ** attempt, _MAX_RETRY_DELAY)


def graphql(query, variables, env):
    key = env.get("LINEAR_API_KEY")
    if not key:
        raise LinearError("LINEAR_API_KEY missing from .env")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Authorization": key, "Content-Type": "application/json"},
    )
    # A single transient blip (rate limit, 5xx, network) otherwise wastes the whole
    # scheduled slot, so retry with backoff. stderr lands in logs/<stage>.log.
    payload = None
    for attempt in range(_MAX_ATTEMPTS):
        last = attempt == _MAX_ATTEMPTS - 1
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_CODES and not last:
                delay = _retry_delay(getattr(e, "headers", None), attempt)
                sys.stderr.write(
                    f"linear: HTTP {e.code}, retry {attempt + 2}/{_MAX_ATTEMPTS} in {delay}s\n")
                time.sleep(delay)
                continue
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                detail = "<unreadable body>"
            raise LinearError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            if not last:
                delay = 2 ** attempt
                sys.stderr.write(
                    f"linear: network error ({e.reason}), "
                    f"retry {attempt + 2}/{_MAX_ATTEMPTS} in {delay}s\n")
                time.sleep(delay)
                continue
            raise LinearError(f"network error: {e.reason}")
        except json.JSONDecodeError as e:
            raise LinearError(f"invalid JSON response from Linear: {e}")
    if payload.get("errors"):
        raise LinearError(json.dumps(payload["errors"]))
    return payload["data"]


# ── read verbs ──────────────────────────────────────────────────────────────

_TEAMS_Q = "query { teams { nodes { id key name } } }"


def cmd_teams(args, env, post=graphql):
    data = post(_TEAMS_Q, {}, env)
    return data["teams"]["nodes"]


_VIEWER_Q = "query { viewer { id name email } }"


def cmd_viewer(args, env, post=graphql):
    """The API key's own user — the usual value for LINEAR_ASSIGNEE_ID."""
    return post(_VIEWER_Q, {}, env)["viewer"]


_PROJECTS_Q = """
query($teamId: String!) {
  team(id: $teamId) { projects(first: 250) { nodes { id name } } }
}"""


def cmd_projects_list(args, env, post=graphql):
    """Projects in the configured team — pick one for LINEAR_PROJECT_ID."""
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_PROJECTS_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    return [{"id": n["id"], "name": n.get("name")}
            for n in data["team"]["projects"]["nodes"]]


_PROJECT_GET_Q = """
query($id: String!) { project(id: $id) { id name description } }"""


def cmd_project_get(args, env, post=graphql):
    """The configured project itself — its description is the roadmap goal."""
    _require_env(env, "LINEAR_PROJECT_ID")
    n = post(_PROJECT_GET_Q, {"id": env.get("LINEAR_PROJECT_ID")}, env)["project"]
    return {"id": n["id"], "name": n.get("name"), "description": n.get("description")}


_ISSUE_FIELDS = """
  id identifier title url description priority createdAt updatedAt canceledAt
  state { name type } assignee { name id }
  labels { nodes { name } } cycle { number }
"""

# Blockers of an issue: inverse relations of type "blocks" — the related node's
# `issue` is the blocker. State + labels are enough to judge dep satisfaction.
_BLOCKERS_F = """
  inverseRelations {
    nodes { type issue { identifier state { name type } labels { nodes { name } } } }
  }
"""

_ISSUES_Q = """
query($filter: IssueFilter, $first: Int!, $after: String) {
  issues(filter: $filter, first: $first, after: $after) {
    nodes { %s %s }
    pageInfo { hasNextPage endCursor }
  }
}""" % (_ISSUE_FIELDS, _BLOCKERS_F)


def _apply_deps(out, n, env):
    """Add blocked_by (declared blocker identifiers) and blocked (any blocker
    not yet satisfied per DEPS_SATISFIED_WHEN) when the node carries relations."""
    nodes = (n.get("inverseRelations") or {}).get("nodes")
    if nodes is None:
        return
    blockers = [r.get("issue") or {} for r in nodes if r.get("type") == "blocks"]
    out["blocked_by"] = [b.get("identifier") for b in blockers]
    mode = dep_mode(env or {})
    out["blocked"] = any(
        not dep_satisfied((b.get("state") or {}).get("type"),
                          [x["name"] for x in (b.get("labels") or {}).get("nodes", [])],
                          mode)
        for b in blockers)


def _shape_issue(n, env=None):
    out = {
        "id": n.get("id"),
        "identifier": n.get("identifier"),
        "title": n.get("title"),
        "url": n.get("url"),
    }
    if "description" in n:
        out["description"] = n.get("description")
    if n.get("priority") is not None:
        out["priority"] = n.get("priority")
    if n.get("createdAt"):
        out["createdAt"] = n.get("createdAt")
    if n.get("updatedAt"):
        out["updatedAt"] = n.get("updatedAt")
    if n.get("canceledAt"):
        out["canceledAt"] = n.get("canceledAt")
    if n.get("state"):
        out["state"] = n["state"].get("name")
        out["state_type"] = n["state"].get("type")
    if n.get("assignee"):
        out["assignee"] = n["assignee"].get("name")
    if n.get("labels"):
        out["labels"] = [x["name"] for x in n["labels"].get("nodes", [])]
    if n.get("cycle"):
        out["cycle"] = n["cycle"].get("number")
    for rel, key in (("comments", "comments"), ("relations", "relations"),
                     ("inverseRelations", "inverseRelations"), ("children", "children"),
                     ("documents", "documents")):
        if n.get(rel):
            out[key] = n[rel].get("nodes", [])
    _apply_deps(out, n, env)
    out["stage"] = stage_of(out.get("labels") or [])
    return out


def _scoped_filter(env):
    _require_env(env, "LINEAR_TEAM_ID", "LINEAR_PROJECT_ID")
    return {
        "team": {"id": {"eq": env.get("LINEAR_TEAM_ID")}},
        "project": {"id": {"eq": env.get("LINEAR_PROJECT_ID")}},
    }


def _issue_nodes(f, env, post=graphql, limit=None):
    remaining = int(limit) if limit else None
    after = None
    nodes = []
    pages = 0
    while True:
        pages += 1
        if pages > 100:  # cheap insurance against an API bug where endCursor never advances
            raise LinearError("issue pagination exceeded 100 pages — endCursor not advancing?")
        first = min(100, remaining) if remaining is not None else 100
        data = post(_ISSUES_Q, {"filter": f, "first": first, "after": after}, env)
        page = data["issues"]
        batch = page.get("nodes", [])
        nodes.extend(batch)
        if remaining is not None:
            remaining -= len(batch)
            if remaining <= 0:
                break
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
        if not after:
            break
    return nodes


def cmd_issues_list(args, env, post=graphql):
    f = _scoped_filter(env)
    if getattr(args, "label", None):
        f["labels"] = {"name": {"eq": args.label}}
    if getattr(args, "state", None):
        f["state"] = {"name": {"eq": args.state}}
    if getattr(args, "assignee", None):
        if args.assignee == "me":
            _require_env(env, "LINEAR_ASSIGNEE_ID")
        uid = env.get("LINEAR_ASSIGNEE_ID") if args.assignee == "me" else args.assignee
        f["assignee"] = {"id": {"eq": uid}}
    nodes = _issue_nodes(f, env, post=post, limit=getattr(args, "limit", None))
    return [_shape_issue(n, env) for n in nodes]


_ISSUE_GET_Q = """
query($id: String!) {
  issue(id: $id) {
    %s
    comments { nodes { body user { name } createdAt } }
    relations { nodes { type relatedIssue { identifier url state { type } } } }
    inverseRelations { nodes { type issue { identifier url state { name type } labels { nodes { name } } } } }
    children { nodes { identifier title url } }
    documents { nodes { id title url } }
  }
}""" % _ISSUE_FIELDS


def cmd_issue_get(args, env, post=graphql):
    _assert_in_scope(args.id, env, post)
    data = post(_ISSUE_GET_Q, {"id": args.id}, env)
    n = data["issue"]
    n["description"] = n.get("description")  # force-keep description on detail read
    return _shape_issue(n, env)


_CYCLES_Q = """
query($teamId: ID!) {
  cycles(filter: { team: { id: { eq: $teamId } } }, first: 50) {
    nodes { id number name startsAt endsAt }
  }
}"""


_DOC_GET_Q = """
query($id: String!) {
  document(id: $id) { id title url content issue { team { id } } }
}"""


def cmd_doc_get(args, env, post=graphql):
    """Fetch a spec document's body by id. Scoped: refuses a document whose issue
    is outside the configured team, so the advance loop can read a spec to verify
    acceptance criteria without reaching across the workspace."""
    _require_env(env, "LINEAR_TEAM_ID")
    doc = post(_DOC_GET_Q, {"id": args.id}, env).get("document")
    if not doc:
        raise LinearError(f"document {args.id} not found")
    team = ((doc.get("issue") or {}).get("team") or {}).get("id")
    if team != env.get("LINEAR_TEAM_ID"):
        raise LinearError(f"document {args.id} is outside the configured team")
    return {"id": doc["id"], "title": doc.get("title"),
            "url": doc.get("url"), "content": doc.get("content")}


def cmd_cycles_list(args, env, post=graphql):
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_CYCLES_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    return [{"id": n["id"], "number": n["number"], "name": n.get("name"),
             "starts_at": n.get("startsAt"), "ends_at": n.get("endsAt")}
            for n in data["cycles"]["nodes"]]


# ── write verbs ─────────────────────────────────────────────────────────────

_LABELS_Q = """
query($teamId: ID!) {
  issueLabels(filter: { or: [{ team: { id: { eq: $teamId } } }, { team: { null: true } }] }, first: 250) {
    nodes { id name }
  }
}"""

_LABEL_CREATE_M = """
mutation($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) { success issueLabel { id name } }
}"""


def cmd_label_ensure(args, env, post=graphql):
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_LABELS_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    for n in data["issueLabels"]["nodes"]:
        if n["name"] == args.name:
            return {"name": n["name"], "id": n["id"], "created": False}
    res = post(_LABEL_CREATE_M,
               {"input": {"name": args.name, "teamId": env.get("LINEAR_TEAM_ID")}},
               env)["issueLabelCreate"]
    return {"name": args.name, "id": res["issueLabel"]["id"], "created": True}


def cmd_labels_list(args, env, post=graphql):
    _require_env(env, "LINEAR_TEAM_ID")
    return post(_LABELS_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)["issueLabels"]["nodes"]


# The full agent:* state-machine vocabulary — single source of truth, mirrors
# docs/LABELS.md. `labels-init` creates any that are missing on the team.
AGENT_LABELS = [
    "agent:spec", "agent:build", "agent:revise",            # human gates
    "agent:auto",                                           # human opt-in: autonomous advancer
    "agent:claimed", "agent:triaged", "agent:needs-human",  # agent status
    "agent:dupe-candidate", "agent:specced", "agent:pr-open",
    "agent:revised", "agent:superseded", "agent:needs-attention",
    "agent:proposed", "agent:later",                        # roadmap proposals
    "agent:hold", "Stale",
]


def cmd_labels_init(args, env, post=graphql):
    _require_env(env, "LINEAR_TEAM_ID")
    team = env.get("LINEAR_TEAM_ID")
    existing = {n["name"] for n in
                post(_LABELS_Q, {"teamId": team}, env)["issueLabels"]["nodes"]}
    created = []
    for name in AGENT_LABELS:
        if name in existing:
            continue
        post(_LABEL_CREATE_M, {"input": {"name": name, "teamId": team}}, env)
        created.append(name)
    return {"created": created,
            "existing": [n for n in AGENT_LABELS if n in existing]}


def _resolve_label_ids(names, env, post):
    if not names:
        return []
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_LABELS_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    by_name = {n["name"]: n["id"] for n in data["issueLabels"]["nodes"]}
    missing = [x for x in names if x not in by_name]
    if missing:
        raise LinearError(
            f"unknown label(s): {', '.join(missing)} — run `cadence labels init`")
    return [by_name[x] for x in names]


_STATES_Q = """
query($teamId: ID!) {
  workflowStates(filter: { team: { id: { eq: $teamId } } }, first: 100) {
    nodes { id name type }
  }
}"""


def _resolve_state_id(name, env, post):
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_STATES_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    for n in data["workflowStates"]["nodes"]:
        if n["name"].lower() == name.lower():
            return n["id"]
    raise LinearError(f"no workflow state named {name!r}")


def _resolve_state_id_by_type(state_type, env, post):
    """First workflow state of the given Linear type (backlog, unstarted, started,
    completed, canceled). Lets callers reach 'the done state' without naming it —
    the name varies per workspace, so no project fact lands in the engine.
    ponytail: first match wins; if a team has several done states, that's the one."""
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_STATES_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    for n in data["workflowStates"]["nodes"]:
        if (n.get("type") or "").lower() == state_type.lower():
            return n["id"]
    raise LinearError(f"no workflow state of type {state_type!r}")


_ISSUE_SCOPE_Q = """
query($id: String!) {
  issue(id: $id) { team { id } project { id } assignee { id } }
}"""


def _assert_in_scope(issue_id, env, post):
    """Hard boundary: refuse to write to an issue outside the configured team /
    project / assignee, even when a prompt hands us an arbitrary id. The personal
    API key can see the whole workspace; the adapter must not act outside scope."""
    _require_env(env, "LINEAR_TEAM_ID", "LINEAR_PROJECT_ID", "LINEAR_ASSIGNEE_ID")
    n = post(_ISSUE_SCOPE_Q, {"id": issue_id}, env).get("issue")
    if not n:
        raise LinearError(f"issue {issue_id} not found")
    if (n.get("team") or {}).get("id") != env.get("LINEAR_TEAM_ID"):
        raise LinearError(f"issue {issue_id} is outside the configured team")
    if (n.get("project") or {}).get("id") != env.get("LINEAR_PROJECT_ID"):
        raise LinearError(f"issue {issue_id} is outside the configured project")
    if (n.get("assignee") or {}).get("id") != env.get("LINEAR_ASSIGNEE_ID"):
        raise LinearError(f"issue {issue_id} is outside the configured assignee")


_ISSUE_GET_LABELS_Q = "query($id: String!){ issue(id:$id){ labels{ nodes{ id name } } } }"

_ISSUE_UPDATE_M = """
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { id } }
}"""


GATE_LABELS = {"agent:spec", "agent:build", "agent:revise"}
DELIVERY_LABELS = {"agent:pr-open", "agent:revised"}
_STAGE_MAY_REMOVE_GATE = {"spec": {"agent:spec"}, "build": {"agent:build"}, "revise": {"agent:revise"}}


def _running_stage(env):
    if "CADENCE_STAGE" not in env:
        return None
    return (env.get("CADENCE_STAGE") or "").strip().lower() or "unknown"


def _autonomous_gate_allowed(stage, add_labels, current_labels, env):
    if stage != "advance":
        return False
    if (env.get("AUTONOMOUS") or "").strip().lower() not in {"1", "on", "true", "yes"}:
        return False
    return "agent:auto" in set(current_labels or []) and all(lbl in GATE_LABELS for lbl in add_labels)


def _guard_gate_removal(remove_labels, env):
    """A scheduled loop must never strip a human gate label; only a human (no
    CADENCE_STAGE key in the environment) or the stage that owns the gate may
    remove it. A present-but-empty CADENCE_STAGE is still a loop context."""
    stage = _running_stage(env)
    if stage is None:
        return
    allowed = _STAGE_MAY_REMOVE_GATE.get(stage, set())
    illegal = sorted(lbl for lbl in remove_labels if lbl in GATE_LABELS and lbl not in allowed)
    if illegal:
        raise LinearError(
            "refused: the %s loop may not remove human gate label(s) %s — only a "
            "human, or the stage that owns the gate, removes it"
            % (stage, ", ".join(illegal)))


def _guard_gate_grant(add_labels, env, current_labels):
    stage = _running_stage(env)
    if stage is None:
        return
    illegal = sorted(lbl for lbl in add_labels if lbl in GATE_LABELS)
    if not illegal:
        return
    if _autonomous_gate_allowed(stage, illegal, current_labels, env):
        return
    raise LinearError(
        "refused: the %s loop may not grant human gate label(s) %s — only a "
        "human, or autonomous advance on an agent:auto issue, grants gates"
        % (stage, ", ".join(illegal)))


def _issue_label_nodes(issue_id, env, post):
    return post(_ISSUE_GET_LABELS_Q, {"id": issue_id}, env)["issue"]["labels"]["nodes"]


def _enforced_label_ids(issue_id, add_names, rem_names, env, post, strip_agent=False):
    """Current labels ± the requested changes, with the single-position invariant
    enforced by resolve_labels (adding a lifecycle label drops the others; stray
    residue self-heals). With strip_agent, also drop every agent:* workflow label
    (used when the issue moves to a terminal state). Returns the labelIds to set.
    Shared by issue-update and bulk-label."""
    nodes = _issue_label_nodes(issue_id, env, post)
    name2id = {n["name"]: n["id"] for n in nodes}
    final = resolve_labels([n["name"] for n in nodes], add=add_names, remove=rem_names)
    if strip_agent:
        final = strip_workflow_labels(final)
    need = [n for n in final if n not in name2id]
    for nm, _id in zip(need, _resolve_label_ids(need, env, post)):
        name2id[nm] = _id
    return [name2id[n] for n in final]


def _target_state_is_terminal(args, env, post):
    """Does this update move the issue to a done/cancelled state? Checks the
    --state-type arg directly, or resolves a --state name to its type."""
    stype = (getattr(args, "state_type", None) or "").lower()
    if stype:
        return stype in _TERMINAL_STATE_TYPES
    name = getattr(args, "state", None)
    if not name:
        return False
    data = post(_STATES_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    for n in data["workflowStates"]["nodes"]:
        if n["name"].lower() == name.lower():
            return (n.get("type") or "").lower() in _TERMINAL_STATE_TYPES
    return False


def cmd_issue_update(args, env, post=graphql):
    _assert_in_scope(args.id, env, post)
    _guard_gate_removal(getattr(args, "remove_label", None) or [], env)
    inp = {}
    if getattr(args, "priority", None) is not None:
        inp["priority"] = int(args.priority)
    if getattr(args, "title", None):
        inp["title"] = args.title
    if getattr(args, "estimate", None) is not None:
        inp["estimate"] = int(args.estimate)
    if getattr(args, "state", None):
        inp["stateId"] = _resolve_state_id(args.state, env, post)
    elif getattr(args, "state_type", None):
        inp["stateId"] = _resolve_state_id_by_type(args.state_type, env, post)
    if getattr(args, "cycle", None):
        inp["cycleId"] = args.cycle  # caller passes a cycle id
    add_names = getattr(args, "add_label", None) or []
    rem_names = getattr(args, "remove_label", None) or []
    current_nodes = None
    if any(lbl in GATE_LABELS for lbl in add_names):
        current_nodes = _issue_label_nodes(args.id, env, post)
        _guard_gate_grant(add_names, env, [n["name"] for n in current_nodes])
    # Moving an issue to a done/cancelled state clears its agent:* workflow labels
    # — a completed issue holds no live gate/status/flag. So a "Set as merged" close
    # tidies the board without a separate label sweep.
    terminal = _target_state_is_terminal(args, env, post)
    had_delivery_label = terminal and any(n["name"] in DELIVERY_LABELS
                                          for n in (current_nodes or _issue_label_nodes(args.id, env, post)))
    if add_names or rem_names or terminal:
        _resolve_label_ids(add_names, env, post)   # fail fast on an unknown add label
        inp["labelIds"] = _enforced_label_ids(args.id, add_names, rem_names, env, post,
                                              strip_agent=terminal)
    if not inp:
        raise LinearError("issue-update: no fields to change")
    res = post(_ISSUE_UPDATE_M, {"id": args.id, "input": inp}, env)["issueUpdate"]
    if not res["success"]:
        raise LinearError("issue-update: Linear returned success=false")
    if had_delivery_label:
        _remove_worktree(args.id.lower(), env)
    return {"id": args.id, "success": res["success"]}


def cmd_bulk_label(args, env, post=graphql):
    """Add/remove label(s) across many issues at once. Targets are either the
    explicit issue ids given, or every in-scope issue carrying --where-label.
    Each issue is scope-checked (team/project/assignee) before mutation. Live
    runs confirm first unless --yes; --dry-run reports the plan without writing."""
    add = args.add_label or []
    rem = args.remove_label or []
    _guard_gate_removal(rem, env)
    if _running_stage(env) is not None and any(lbl in GATE_LABELS for lbl in add):
        raise LinearError(
            "refused: the %s loop may not bulk-grant human gate label(s) %s"
            % (_running_stage(env), ", ".join(sorted(lbl for lbl in add if lbl in GATE_LABELS))))
    if not add and not rem:
        raise LinearError("bulk-label: nothing to do (need --add and/or --remove)")
    if args.where_label and args.issues:
        raise LinearError("bulk-label: give issue ids OR --where-label, not both")

    if args.where_label:
        f = _scoped_filter(env)
        f["labels"] = {"name": {"eq": args.where_label}}
        if env.get("LINEAR_ASSIGNEE_ID"):
            f["assignee"] = {"id": {"eq": env.get("LINEAR_ASSIGNEE_ID")}}
        nodes = _issue_nodes(f, env, post=post)
        targets = [n["identifier"] for n in nodes]
    else:
        targets = list(args.issues or [])

    if not targets:
        return {"updated": [], "errors": [], "note": "no target issues matched"}

    plan = {"add": add, "remove": rem, "targets": targets, "count": len(targets)}
    if args.dry_run:
        plan["dry_run"] = True
        return plan

    if not args.yes:
        sys.stderr.write(
            "bulk-label: add %s / remove %s on %d issue(s):\n  %s\nProceed? [y/N] "
            % (", ".join(add) or "—", ", ".join(rem) or "—", len(targets), ", ".join(targets)))
        sys.stderr.flush()
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return {"aborted": True, "count": len(targets)}

    _resolve_label_ids(add, env, post)   # fail fast on an unknown add label
    updated, errors = [], []
    for ident in targets:
        try:
            _assert_in_scope(ident, env, post)
            ids = _enforced_label_ids(ident, add, rem, env, post)
            post(_ISSUE_UPDATE_M, {"id": ident, "input": {"labelIds": ids}}, env)
            updated.append(ident)
        except LinearError as e:
            errors.append({"issue": ident, "error": str(e)})
    return {"updated": updated, "errors": errors, "count": len(updated)}


_COMMENT_M = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id } }
}"""


def cmd_issue_comment(args, env, post=graphql):
    _assert_in_scope(args.id, env, post)
    res = post(_COMMENT_M, {"input": {"issueId": args.id, "body": args.body}},
               env)["commentCreate"]
    return {"id": args.id, "success": res["success"]}


_RELATE_M = """
mutation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) { success }
}"""


def cmd_issue_relate(args, env, post=graphql):
    _assert_in_scope(args.a, env, post)
    _assert_in_scope(args.b, env, post)
    res = post(_RELATE_M,
               {"input": {"issueId": args.a, "relatedIssueId": args.b,
                          "type": args.type}}, env)["issueRelationCreate"]
    return {"success": res["success"]}


_DOC_CREATE_M = """
mutation($input: DocumentCreateInput!) {
  documentCreate(input: $input) { success document { id url } }
}"""
_DOC_UPDATE_M = """
mutation($id: String!, $input: DocumentUpdateInput!) {
  documentUpdate(id: $id, input: $input) { success document { id url } }
}"""

_DOC_SCOPE_Q = """
query($id: String!) {
  document(id: $id) {
    id
    issue { id team { id } project { id } assignee { id } }
  }
}"""


def _assert_document_matches_issue(doc_id, issue_id, env, post):
    doc = post(_DOC_SCOPE_Q, {"id": doc_id}, env).get("document")
    if not doc:
        raise LinearError(f"document {doc_id} not found")
    issue = doc.get("issue")
    if not issue:
        raise LinearError(f"document {doc_id} is not linked to an issue")
    if issue.get("id") != issue_id:
        raise LinearError(f"document {doc_id} is not linked to issue {issue_id}")
    if (issue.get("team") or {}).get("id") != env.get("LINEAR_TEAM_ID"):
        raise LinearError(f"document {doc_id} is outside the configured team")
    if (issue.get("project") or {}).get("id") != env.get("LINEAR_PROJECT_ID"):
        raise LinearError(f"document {doc_id} is outside the configured project")
    if (issue.get("assignee") or {}).get("id") != env.get("LINEAR_ASSIGNEE_ID"):
        raise LinearError(f"document {doc_id} is outside the configured assignee")


def cmd_doc_upsert(args, env, post=graphql):
    _assert_in_scope(args.issue, env, post)
    if getattr(args, "doc_id", None):
        _assert_document_matches_issue(args.doc_id, args.issue, env, post)
        res = post(_DOC_UPDATE_M, {"id": args.doc_id,
                   "input": {"title": args.title, "content": args.body}},
                   env)["documentUpdate"]
    else:
        res = post(_DOC_CREATE_M, {"input": {
            "title": args.title, "content": args.body, "issueId": args.issue}},
            env)["documentCreate"]
    return {"id": res["document"]["id"], "url": res["document"]["url"]}


_TERMINAL_STATE_TYPES = {"completed", "canceled"}

_ISSUE_CREATE_M = """
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}"""


def _open_proposal_count(env, post):
    f = _scoped_filter(env)
    f["labels"] = {"name": {"eq": "agent:proposed"}}
    nodes = _issue_nodes(f, env, post=post)
    return sum(1 for n in nodes
               if ((n.get("state") or {}).get("type")) not in _TERMINAL_STATE_TYPES)


def cmd_issue_create(args, env, post=graphql):
    """File a roadmap proposal. Always carries agent:proposed, always scoped to
    the configured team/project/assignee, and refuses to exceed ROADMAP_MAX_OPEN
    open proposals — the cap is engine-enforced, not prompt-promised."""
    _require_env(env, "LINEAR_TEAM_ID", "LINEAR_PROJECT_ID", "LINEAR_ASSIGNEE_ID")
    try:
        max_open = int(env.get("ROADMAP_MAX_OPEN") or 5)
    except ValueError:
        max_open = 5
    open_now = _open_proposal_count(env, post)
    if open_now >= max_open:
        raise LinearError(
            f"roadmap cap reached: {open_now} open proposal(s) (ROADMAP_MAX_OPEN={max_open})")
    with open(args.body_file, encoding="utf-8") as f:
        description = f.read().strip()
    names = ["agent:proposed"] + [x for x in (args.label or []) if x != "agent:proposed"]
    label_ids = _resolve_label_ids(names, env, post)
    res = post(_ISSUE_CREATE_M, {"input": {
        "teamId": env.get("LINEAR_TEAM_ID"),
        "projectId": env.get("LINEAR_PROJECT_ID"),
        "assigneeId": env.get("LINEAR_ASSIGNEE_ID"),
        "title": args.title,
        "description": description,
        "labelIds": label_ids,
    }}, env)["issueCreate"]
    issue = res["issue"]
    return {"id": issue["id"], "identifier": issue["identifier"],
            "url": issue["url"], "success": res["success"]}


def _build_parser():
    p = argparse.ArgumentParser(prog="cadence linear")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("teams")
    sub.add_parser("me")
    sub.add_parser("projects")
    sub.add_parser("project-get")
    il = sub.add_parser("issues-list"); il.add_argument("--label")
    il.add_argument("--state"); il.add_argument("--assignee")
    il.add_argument("--limit", type=int)
    g = sub.add_parser("issue-get"); g.add_argument("id")
    u = sub.add_parser("issue-update"); u.add_argument("id")
    u.add_argument("--priority", type=int); u.add_argument("--state")
    u.add_argument("--state-type", dest="state_type")
    u.add_argument("--title"); u.add_argument("--estimate", type=int)
    u.add_argument("--cycle")
    u.add_argument("--add-label", action="append", dest="add_label")
    u.add_argument("--remove-label", action="append", dest="remove_label")
    bl = sub.add_parser("bulk-label")
    bl.add_argument("issues", nargs="*")
    bl.add_argument("--where-label", dest="where_label")
    bl.add_argument("--add", action="append", dest="add_label")
    bl.add_argument("--remove", action="append", dest="remove_label")
    bl.add_argument("--dry-run", action="store_true", dest="dry_run")
    bl.add_argument("-y", "--yes", action="store_true")
    c = sub.add_parser("issue-comment"); c.add_argument("id"); c.add_argument("body")
    r = sub.add_parser("issue-relate"); r.add_argument("a"); r.add_argument("b")
    r.add_argument("--type", choices=["duplicate", "related", "blocks"], default="related")
    le = sub.add_parser("label-ensure"); le.add_argument("name")
    sub.add_parser("labels-list")
    sub.add_parser("labels-init")
    d = sub.add_parser("doc-upsert"); d.add_argument("--issue", required=True)
    d.add_argument("--title", required=True); d.add_argument("--body", required=True)
    d.add_argument("--doc-id", dest="doc_id")
    dg = sub.add_parser("doc-get"); dg.add_argument("id")
    sub.add_parser("cycles-list")
    ic = sub.add_parser("issue-create")
    ic.add_argument("--title", required=True)
    ic.add_argument("--body-file", required=True, dest="body_file")
    ic.add_argument("--label", action="append")
    return p


_DISPATCH = {
    "teams": cmd_teams, "me": cmd_viewer, "projects": cmd_projects_list,
    "project-get": cmd_project_get,
    "issues-list": cmd_issues_list, "issue-get": cmd_issue_get,
    "issue-update": cmd_issue_update, "bulk-label": cmd_bulk_label,
    "issue-comment": cmd_issue_comment,
    "issue-relate": cmd_issue_relate, "label-ensure": cmd_label_ensure,
    "labels-list": cmd_labels_list, "labels-init": cmd_labels_init,
    "doc-upsert": cmd_doc_upsert, "doc-get": cmd_doc_get,
    "cycles-list": cmd_cycles_list,
    "issue-create": cmd_issue_create,
}


def main(argv=None):
    args = _build_parser().parse_args(argv)
    env = load_env()
    try:
        result = _DISPATCH[args.cmd](args, env)
    except LinearError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
