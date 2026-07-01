"""Cadence Linear adapter — speaks the Linear GraphQL API. Stdlib only.

Replaces the Linear MCP. Reads ids/key from .env (via cadence_env). Each cmd_*
is `cmd_x(args, env, post=graphql)`; pass a fake post in tests. main() prints
the result as JSON.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cadence_env import load_env  # noqa: E402

API_URL = "https://api.linear.app/graphql"


class LinearError(RuntimeError):
    pass


def _require_env(env, *names):
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise LinearError(f"missing required env value(s): {', '.join(missing)}")


def graphql(query, variables, env):
    key = env.get("LINEAR_API_KEY")
    if not key:
        raise LinearError("LINEAR_API_KEY missing from .env")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Authorization": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LinearError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
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


_ISSUE_FIELDS = """
  id identifier title url description priority createdAt
  state { name type } assignee { name id }
  labels { nodes { name } } cycle { number }
"""

_ISSUES_Q = """
query($filter: IssueFilter, $first: Int!, $after: String) {
  issues(filter: $filter, first: $first, after: $after) {
    nodes { %s }
    pageInfo { hasNextPage endCursor }
  }
}""" % _ISSUE_FIELDS


def _shape_issue(n):
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
                     ("inverseRelations", "inverseRelations"), ("children", "children")):
        if n.get(rel):
            out[key] = n[rel].get("nodes", [])
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
    while True:
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
    return [_shape_issue(n) for n in nodes]


_ISSUE_GET_Q = """
query($id: String!) {
  issue(id: $id) {
    %s
    comments { nodes { body user { name } createdAt } }
    relations { nodes { type relatedIssue { identifier url state { type } } } }
    inverseRelations { nodes { type issue { identifier url state { type } } } }
    children { nodes { identifier title url } }
  }
}""" % _ISSUE_FIELDS


def cmd_issue_get(args, env, post=graphql):
    _assert_in_scope(args.id, env, post)
    data = post(_ISSUE_GET_Q, {"id": args.id}, env)
    n = data["issue"]
    n["description"] = n.get("description")  # force-keep description on detail read
    return _shape_issue(n)


_CYCLES_Q = """
query($teamId: ID!) {
  cycles(filter: { team: { id: { eq: $teamId } } }, first: 50) {
    nodes { id number name startsAt endsAt }
  }
}"""


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
    nodes { id name }
  }
}"""


def _resolve_state_id(name, env, post):
    _require_env(env, "LINEAR_TEAM_ID")
    data = post(_STATES_Q, {"teamId": env.get("LINEAR_TEAM_ID")}, env)
    for n in data["workflowStates"]["nodes"]:
        if n["name"].lower() == name.lower():
            return n["id"]
    raise LinearError(f"no workflow state named {name!r}")


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


_ISSUE_GET_LABELS_Q = "query($id: String!){ issue(id:$id){ labels{ nodes{ id } } } }"

_ISSUE_UPDATE_M = """
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { id } }
}"""


def cmd_issue_update(args, env, post=graphql):
    _assert_in_scope(args.id, env, post)
    inp = {}
    if getattr(args, "priority", None) is not None:
        inp["priority"] = int(args.priority)
    if getattr(args, "title", None):
        inp["title"] = args.title
    if getattr(args, "estimate", None) is not None:
        inp["estimate"] = int(args.estimate)
    if getattr(args, "state", None):
        inp["stateId"] = _resolve_state_id(args.state, env, post)
    if getattr(args, "cycle", None):
        inp["cycleId"] = args.cycle  # caller passes a cycle id
    add = _resolve_label_ids(getattr(args, "add_label", None) or [], env, post)
    rem = set(_resolve_label_ids(getattr(args, "remove_label", None) or [], env, post))
    if add or rem:
        current = post(_ISSUE_GET_LABELS_Q, {"id": args.id}, env)["issue"]
        ids = {x["id"] for x in current["labels"]["nodes"]}
        ids |= set(add)
        ids -= rem
        inp["labelIds"] = list(ids)
    if not inp:
        raise LinearError("issue-update: no fields to change")
    res = post(_ISSUE_UPDATE_M, {"id": args.id, "input": inp}, env)["issueUpdate"]
    return {"id": args.id, "success": res["success"]}


def cmd_bulk_label(args, env, post=graphql):
    """Add/remove label(s) across many issues at once. Targets are either the
    explicit issue ids given, or every in-scope issue carrying --where-label.
    Each issue is scope-checked (team/project/assignee) before mutation. Live
    runs confirm first unless --yes; --dry-run reports the plan without writing."""
    add = args.add_label or []
    rem = args.remove_label or []
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

    add_ids = _resolve_label_ids(add, env, post)
    rem_ids = set(_resolve_label_ids(rem, env, post))
    updated, errors = [], []
    for ident in targets:
        try:
            _assert_in_scope(ident, env, post)
            current = post(_ISSUE_GET_LABELS_Q, {"id": ident}, env)["issue"]
            ids = {x["id"] for x in current["labels"]["nodes"]}
            ids |= set(add_ids)
            ids -= rem_ids
            post(_ISSUE_UPDATE_M, {"id": ident, "input": {"labelIds": list(ids)}}, env)
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


def _build_parser():
    p = argparse.ArgumentParser(prog="cadence linear")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("teams")
    il = sub.add_parser("issues-list"); il.add_argument("--label")
    il.add_argument("--state"); il.add_argument("--assignee")
    il.add_argument("--limit", type=int)
    g = sub.add_parser("issue-get"); g.add_argument("id")
    u = sub.add_parser("issue-update"); u.add_argument("id")
    u.add_argument("--priority", type=int); u.add_argument("--state")
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
    sub.add_parser("cycles-list")
    return p


_DISPATCH = {
    "teams": cmd_teams, "issues-list": cmd_issues_list, "issue-get": cmd_issue_get,
    "issue-update": cmd_issue_update, "bulk-label": cmd_bulk_label,
    "issue-comment": cmd_issue_comment,
    "issue-relate": cmd_issue_relate, "label-ensure": cmd_label_ensure,
    "labels-list": cmd_labels_list, "labels-init": cmd_labels_init,
    "doc-upsert": cmd_doc_upsert, "cycles-list": cmd_cycles_list,
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
