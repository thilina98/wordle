# Vendored libraries

Copied into the repo rather than loaded from a CDN, so the page depends on no
third-party host at runtime and a library update is a reviewed commit.

| File | Library | Version | Source | Licence |
|---|---|---|---|---|
| `oidc-client-ts-3.4.1.min.js` | oidc-client-ts | 3.4.1 | `npm pack oidc-client-ts@3.4.1`, file `dist/browser/oidc-client-ts.min.js` | Apache-2.0, see `oidc-client-ts-3.4.1.LICENSE` |

It defines one global, `oidc`. Only `auth.js` uses it.

To update: `npm pack oidc-client-ts@<version>`, copy the same file under the
new version's name, update `index.html`, `Dockerfile` and this table.
