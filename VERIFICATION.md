# Publication-preparation verification

Checked on 14 November 2026. Original research repository remains private; this new synthetic repository uses fresh history.

- After retiring the private-artifact baseline test, **58 unittest tests passed**.
  The same **58 tests passed from a fresh local clone** with no artifacts or raw
  cache present. They used the existing installed dependencies; research experiment
  tests create and load only their own temporary synthetic model fixtures.
- Fresh-clone homepage/API checks passed and confirmed imports came from the clone.
  A clean CPython 3.12.4 venv was created successfully. Dependency installation in
  that new venv was **not run**: the offline wheel cache was empty. Thus full clean
  dependency installation/lock resolution is not claimed. `pip check` passed in
  the tested environment; `requirements-lock.txt` records its versions.
- Installed Playwright/Chromium passed seven smoke-check groups: fictional banner,
  search/report, model labels, previous-value scenario, invalid input, no fake
  evaluation, and mobile layout/no uncaught errors/no external assets. A deliberate
  invalid-input request returned the expected 422 console network error.
- No package/browser/runtime download, real dataset download or PitchAPI request
  was performed for publication preparation.
- History review initially scanned 45 reachable commits/166 blobs, then 46/178
  after the first cleanup commit. No known provider token/private key pattern was
  found; eight generic historical object findings were fixed test fixtures. Raw
  values were not printed. Personal paths, author metadata, older data/models and
  screenshots remain in history and block publication. Detailed bounded scope and
  limitations are in `docs/RELEASE_READINESS.md`.
- Model-execution correction: an initially missed baseline test loaded the private
  model during the first working-tree suite. Fresh-clone verification exposed the
  dependency. That test/loader were removed; subsequent clean checks do not load
  private models. Byte inspection is not a model-safety certification.
- Dataset/model/provider exports and screenshots were untracked at HEAD, preserving
  local copies under ignore rules. Current app uses original synthetic fixtures.
  Third-party rights and code MIT scope are separated in the notices.
- Profile README replaced Campus Connect with accurate Touchline technologies and
  **Private ? publication preparation**, without a misleading public project link.
- The user subsequently authorized a fresh sanitized repository. No original
  history is rewritten or force-pushed. New history is separately scanned before publication.

This record describes checks actually run, not a complete security/legal review.
