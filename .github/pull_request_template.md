<!-- Thank you for your contribution. Keep the pull request small and focused. -->

## What and why

<!-- Describe the change. Describe the problem that it solves. Link the issue: "Closes #123". -->

## How you tested it

<!-- List the tests that you added or ran. Add the summary line from `python -m unittest discover -s tests`. -->

## Checklist

- [ ] You added or updated the tests, and `python -m unittest discover -s tests` passes.
- [ ] The standard-library core (`config`, `registry`, `claude_env`, `migrate`, `cli`) gets no new dependency, or you give the reason above.
- [ ] The tests do not read or change a real `~/.claude` or `~/.config/smart-router`. They use temporary directories or the fake-home fixture.
- [ ] You updated the documents (README or docstrings) when the behavior changed.
- [ ] The commit messages use Conventional Commits.
