# Issue tracker: GitHub

Issues and specs live in GitHub Issues for `jsmatfess/chopper`.
Use the `gh` CLI with `--repo jsmatfess/chopper`.

GitHub Issues is the active backlog and specification tracker. Keep status,
acceptance criteria and dependencies in the owning issue instead of maintaining
a parallel repository checklist. Historical checklists and research remain
reference material. An issue's existence does not authorize implementation.

## Operations

- Publish to the tracker: create a GitHub issue.
- Fetch a ticket: read its body, labels and comments with
  `gh issue view <number> --repo jsmatfess/chopper --json number,title,body,labels,comments`.
- Create issues and comments using `--body-file` for multiline text.
- Apply or remove labels with `gh issue edit`.
- Before closing an issue, post an explanation with `gh issue comment`.

Use native GitHub sub-issues and dependencies when supported.
Otherwise, put `Part of #<parent>` and `Blocked by: #<number>`
at the top of the child body, and list children in the parent.
An issue is unblocked when every blocker is closed.

Verify the target repository before creating issues; create them
only in the user's repository.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding

A map is an issue labelled `wayfinder:map`, with Notes,
Decisions-so-far and Fog sections. Link child tickets as sub-issues,
or use a task list and `Part of` references.

Label children `wayfinder:<type>`, where type is research,
prototype, grilling or task. The frontier is the first open child
in map order with no open blockers and no assignee.

Claim a ticket by assigning yourself. Resolve it by commenting,
closing it and adding a finding plus link to the map's
Decisions-so-far.
