# Issue tracker: GitHub

Issues and product requirements for this repository live in GitHub Issues for `wkguoo/paper-scraper-doi`. Use the `gh` CLI from this clone when an engineering skill needs to read or publish an issue.

## Conventions

- Create an issue: `gh issue create --title "..." --body "..."`.
- Read an issue: `gh issue view <number> --comments`.
- List issues: `gh issue list --state open` with an appropriate label filter.
- Comment, edit labels, or close an issue only when the current task explicitly authorizes that external change.

## Pull requests as a triage surface

**PRs as a request surface: no.**

External pull requests are not automatically treated as incoming feature requests.

## Skill routing

When an engineering skill says to publish work to the issue tracker, create a GitHub Issue. When it says to fetch a ticket, run `gh issue view <number> --comments`.
