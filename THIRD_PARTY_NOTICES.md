# Code, dependency and asset notices

`LICENSE` applies to Ankit Chaurasia's original application, tests, documentation,
CSS geometry/favicon and deterministic synthetic generator in this release tree.
Git authorship and this project's development record support that attribution;
no separately attributed third-party source bundle was identified. This is not
a warranty of exhaustive ownership clearance.

It does **not** relicense historical datasets, provider responses, learned models,
player photographs, badges, or dependency distributions. See `DATA_NOTICES.md`.
Dependencies retain their own licenses and notices when installed:

| Dependency family | Declared upstream license / source |
|---|---|
| FastAPI | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Uvicorn, Starlette, HTTPX | BSD-3-Clause; [Encode](https://github.com/encode) upstream projects |
| NumPy | Installed metadata: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; retain bundled component notices |
| pandas, SciPy, scikit-learn | BSD-3-Clause family; respective upstream project/component license files |
| joblib | BSD-3-Clause; [upstream](https://github.com/joblib/joblib/blob/main/LICENSE.txt) |
| Pydantic | MIT; [upstream](https://github.com/pydantic/pydantic/blob/main/LICENSE) |
| certifi | MPL-2.0; its certificate bundle is supplied by the installed dependency |

These dependencies are imported, not vendored or relicensed under MIT. The tested
environment is recorded in `requirements-lock.txt`; installers must retain the
licenses accompanying wheels. No external fonts, player images, provider logos,
or screenshots are shipped in the proposed public tree. System fonts provide the
fallback when named fonts are unavailable.
