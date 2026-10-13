# Third-party software notices

Portfolio Analyser is distributed under GPL-3.0-only. It uses third-party libraries that retain their own copyright and license terms. The repository is source-only: `frontend/node_modules/`, Python environments, and built frontend bundles are not source inputs and must not be committed. Dependency manifests identify the declared dependencies; the frontend lockfile records the resolved JavaScript dependency tree. Preserve notices supplied by each dependency when redistributing a build.

The following is an inventory of direct dependencies, based on the current manifests and locally installed package metadata. It is not a substitute for reviewing the complete resolved transitive dependency tree when preparing a release.

## Backend

| Dependency | License reported by package metadata |
| --- | --- |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| Pydantic | MIT |
| pytest | MIT |
| python-multipart | Apache-2.0 |
| ReportLab | ReportLab BSD-style license; see the package's `license.txt` |
| Matplotlib | Python Software Foundation License; see the package license text |
| Pillow | MIT-CMU |
| yfinance | Apache-2.0 |

## Frontend

| Dependency | License reported by package metadata |
| --- | --- |
| React and React DOM | MIT |
| Recharts | MIT |
| lucide-react | ISC |
| Vite and `@vitejs/plugin-react` | MIT |
| TypeScript | Apache-2.0 |
| Vitest | MIT |
| Testing Library packages | MIT |
| React type declarations (`@types/react`, `@types/react-dom`) | MIT |
| jsdom | MIT |

Keep each dependency's license file and copyright notices intact. Before publishing a release or adding a dependency, review the exact resolved versions (including transitive packages), any bundled assets, and compatibility with GPL-3.0-only. Resolve unknown, missing, or restrictive licenses before distribution.

The locally resolved frontend tree also contains Apache-2.0, BSD-2-Clause, BSD-3-Clause, MIT-0, CC0-1.0, and CC-BY-4.0 packages. In particular, `caniuse-lite` provides browser-support data under CC-BY-4.0; its attribution and license must be retained if that data is redistributed. The installed backend dependency tree includes `chardet` (LGPL-2.1-or-later), `frozendict` (LGPL-3.0), and `certifi` (MPL-2.0), alongside MIT, BSD, Apache, and PSF-licensed packages. Their package distributions carry the applicable license texts. The backend manifest pins direct dependencies but not the complete transitive tree, so refresh this review against the actual environment used for any binary/container distribution.
