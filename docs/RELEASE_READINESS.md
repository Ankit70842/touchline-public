# Clean synthetic release review

Prepared 14 November 2026. The user explicitly authorized a new repository with
fresh history after reviewing the original repository's publication blockers.
This tree was exported with `git archive` from the sanitized source; no original
`.git`, data, environment, cached responses, images or model binaries were copied.

Original source review covered 49 reachable commits and 193 unique blobs. Known
provider-token/private-key patterns found no matches; eight generic historical
findings were fixed test fixtures. Historical personal paths, author metadata,
provider data/models and screenshots keep the source archive private. They are
not present in this new repository's commit graph.

The source app and a fresh clone passed 58 fixture-only tests, and installed
Playwright/Chromium passed seven smoke-check groups. Dependency consistency and
clean native venv creation passed. A fully isolated dependency installation was
not run (no offline wheels), and no live CVE scanner was installed. These limits
are documented rather than presented as completed checks.

The initial private-model baseline test was found during source preparation and
retired with its loader. Current app never loads local pickles or private data.
Remaining research tests generate only their own trusted temporary fixtures.

Original code/docs and the fictional generator use MIT. No provider redistribution
permission was inferred: all affected material was excluded. Dependencies retain
their licenses; see `DATA_NOTICES.md` and `THIRD_PARTY_NOTICES.md`.

This is a bounded publication review, not a complete security audit or legal
certification. Current-tree and entire fresh-history scans are required before
visibility changes. The original private repository must not be made public as a
side effect of this release.
