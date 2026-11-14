# Data provenance and redistribution decisions

Reviewed 14 November 2026 (Asia/Calcutta). Code licensing does not grant data rights.

| Material in earlier private commits | Provenance | Evidence / restrictions | Release decision |
|---|---|---|---|
| Player snapshots, histories and values (`artifacts/players.json`, `history.json`, metadata) | Kaggle `davidcariboo/player-scores`, sourced from dcaribou/transfermarkt-datasets and Transfermarkt | [Upstream LICENSE](https://raw.githubusercontent.com/dcaribou/transfermarkt-datasets/master/LICENSE) declares CC0-1.0; [upstream provenance](https://github.com/dcaribou/transfermarkt-datasets). Kaggle page returned no readable license content in this review. Transfermarkt's [terms](https://www.transfermarkt.com/intern/anb) showed a verification screen, not accessible terms. No access control was bypassed. CC0 covers only rights its affirmer can grant; upstream third-party/database rights were not established. | Withheld from HEAD; no redistribution permission inferred from availability. |
| Serialized predictors and evaluation/prediction exports | Locally trained on the preceding data; sklearn/joblib serialization | Weights, predictions and metrics are derived from the same unverified-rights source. No independent model/data redistribution grant established. Pickle/joblib can execute code; byte inspection is not a safety proof. | Withheld; release app never loads them. An initially missed legacy test did load the private baseline; it and its loader were retired. See the correction in the review report. |
| PitchAPI player-match records, mappings, fixtures, audits and pilot exports (`artifacts/pitchapi/`) | Cached PitchAPI responses plus Transfermarkt-derived labels and independent public identity evidence | [Official reference](https://pitchapi.dev/) documents access, keys and fields, but no redistribution license was found. `/terms` was not accessible. Free/unlimited access is not a redistribution grant. | Withheld, including compact derivative exports. Obtain explicit provider and underlying-data permission before redistribution. |
| Identity/season evidence | Brentford official match report, Sky lineup, indexed Transfermarkt profiles, Opta career records and Fixture Download checklist; URLs were recorded in earlier private artifacts | Public readability/attribution does not establish permission to repackage tables or provider-derived records. | No source tables, screenshots or copies shipped. Earlier pilot remains private research evidence. |
| UI screenshots (`docs/*.png`) | Agent-captured local app screens displaying the preceding real football values | No obvious desktop/private-window content found in the current screenshot reviewed; historical screenshot objects remain. Visible underlying data inherits unresolved rights. | All screenshots withheld from release tree. |
| Football images/badges referenced in cached responses | Provider CDN URLs | No image/trademark redistribution grant established. No downloaded image assets were identified in the tracked tree. | No provider images or badges shipped. Raw cache remains local/ignored. |
| Current synthetic demo | `touchline/demo.py`, original deterministic arithmetic and fictional players/clubs | Created for this release; not sampled from real records or trained weights. Dates/prices are examples, not actual football evidence. | Distributed with original code under MIT. |

[CC0's official legal code](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en)
limits what an affirmer can grant and disclaims third-party-rights clearance. This
review found uncertainty, not a legal determination that every historical fact is
protected. The conservative publication decision is to withhold disputed material.

## Permitted reproducible alternative

The app generates fictional data in memory on startup, requiring no account,
download, model binary or API key. Search, reports, comparisons and validated
scenarios remain functional. The illustration is not a trained valuation model;
its bands have no measured coverage and no market accuracy is claimed.

Research modules can be tested with synthetic fixtures. For independent research,
users may supply data locally only after establishing their own access/use and
redistribution rights; those files must remain ignored. The public app intentionally
does not auto-discover local artifacts or deserialize user-supplied models. No
automatic source downloader is shipped.

## Historical source repository

The original research repository remains private because its older reachable
commits contain the withheld material. This separately authorized clean repository
starts with fresh history containing only the reviewed synthetic tree. No old
Git objects or private caches were transferred. Rights uncertainty was addressed
by exclusion, not by granting MIT to provider material.
