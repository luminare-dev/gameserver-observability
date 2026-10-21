# Choosing the licence

This folder holds unchanged reference copies of the three licences used across the organization's
repositories. A new repository keeps exactly one of them as its `LICENSE` file. Checked on
2026-10-06 against the sources below.

| File | SPDX id | Source |
|---|---|---|
| [Apache-2.0.txt](Apache-2.0.txt) | `Apache-2.0` | <https://www.apache.org/licenses/LICENSE-2.0.txt> (sha256 `cfc7749b…bc523d30`) |
| [MIT.txt](MIT.txt) | `MIT` | SPDX License List 3.29.0, `text/MIT.txt` |
| [MIT-0.txt](MIT-0.txt) | `MIT-0` | SPDX License List 3.29.0, `text/MIT-0.txt` |

## Which licence

| Project type | Licence | Why |
|---|---|---|
| Infrastructure code: Ansible collections and roles, infrastructure-as-code repositories, Prometheus rules, Grafana dashboards, exporters | **Apache-2.0** | The norm in the Ansible, Prometheus and Terraform ecosystems. Adds an explicit patent grant and states that contributions come under the same licence (section 5). |
| Tools, applications, libraries, PowerShell modules, documentation repositories, this template and the organization's `.github` repository | **MIT** | Short and permissive; the most common choice for small tools and libraries. |
| Starter files that users copy into their own projects (for example the files a project template generates) | **MIT-0** | Like MIT, but copies need no attribution, so users do not have to carry a notice into their own work. Only for those files; the rest of the repository stays MIT. |
| Written posts and articles | CC BY 4.0 | Not code; published outside these repositories. |

Never publish a repository without a licence file: without one, nobody may legally reuse the
code. Never copy GPL-licensed code into an MIT or Apache-2.0 repository.

## How to apply it in a new repository

1. **LICENSE.** Copy the chosen file to `LICENSE` in the repository root. Do this in every new
   repository, even when MIT is kept: the template's own `LICENSE` carries the template's year.
   - MIT: replace `<year> <copyright holders>` in the copyright line with the year of first
     publication and the copyright holder, in the same form as in `NOTICE`.
   - Apache-2.0: copy the text unchanged, including the appendix. The copyright line goes into
     `NOTICE`, not into `LICENSE`.
2. **NOTICE.** Use the `NOTICE` that brand-repos generates for the repository slug (it names the
   licence, excludes the brand and keeps the font's OFL). In an Apache-2.0 repository this file is
   the `NOTICE` that section 4(d) of the licence refers to; keep it short.
3. **README.** Fill the `SPDX_ID` placeholder in the Licence section.
4. **SPDX headers (optional, recommended for MIT-0 files).** Source files may start with a comment
   such as `SPDX-License-Identifier: Apache-2.0`. Files under MIT-0 must carry
   `SPDX-License-Identifier: MIT-0`, and the repository then keeps `licenses/MIT-0.txt`.
5. **Clean up.** Delete `licenses/`, including this file, and the `licenses/*.txt` line in
   `.forbidden-words-allow`. Keep only `licenses/MIT-0.txt` when some files are MIT-0.
6. **Third-party code.** Anything vendored keeps its own licence; list it in
   `THIRD_PARTY_NOTICES.md` with name, version, licence and source URL.

## Contributions

Every repository uses the Developer Certificate of Origin (`git commit -s`) with "inbound =
outbound": a contribution comes under the repository's licence, and the contributor keeps the
copyright (see the organization's
[CONTRIBUTING.md](https://github.com/luminare-dev/.github/blob/main/CONTRIBUTING.md)). There is no
Contributor License Agreement, so changing a repository's licence later needs the agreement of
every contributor whose code is still in it. Choose carefully before the first outside
contribution.
