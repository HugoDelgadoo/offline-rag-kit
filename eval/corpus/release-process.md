# Release process

Releases are cut every second Tuesday from the main branch after the full test suite passes.

A release candidate is deployed to the staging environment and tested for at least 24 hours before production deployment.

If a critical bug is found in production, the team rolls back to the previous version first and prepares a hotfix afterwards.
