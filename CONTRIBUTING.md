# Contributing

Thank you for helping make private document search more accessible.

1. Open an issue describing a real bug, a reproducible input, or a small feature proposal.
2. Fork the repository and create a branch from `main`.
3. Add or update tests and documentation together with your change.
4. Run `python -m unittest discover -s tests -v` and `ruff check .` locally (CI also runs the tests on Windows and macOS and requires 80% coverage).
5. Submit a pull request explaining behavior, trade-offs, and any privacy impact.

Do not upload private documents, user secrets, production credentials or non-redistributable sample data. If AI tools assisted your changes, review the code yourself and disclose their role when relevant. Maintainers review PRs for security and correctness before merging.

Good first issues: documentation improvements, additional test cases, robust PDF parsing, and clearer failure messages.
