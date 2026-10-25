# DrainCheck collaboration instructions

The user has explicitly requested that this application and future tested
updates be uploaded to **git@github.com:YoanTrendafilov2002/DrainCheck.git**.
This is the durable project instruction for subsequent work on this repository.

- Implement the requested change, perform meaningful validation, and inspect
  the diff before committing. Preserve unrelated user changes. After a tested
  update, commit the intended project files and push the normal branch update
  to this repository, unless the user explicitly asks to keep that work local.
- Use the existing configured remote and branch; the shared application branch
  is `main`. Never force-push, rewrite published history, delete remote branches
  or alter repository visibility without a separate explicit request.
- If authentication or remote access prevents a push, finish the local work
  and validation, preserve a reviewable commit when possible, and report the
  exact remaining access problem. Never claim a push succeeded without its
  successful result. Do not bypass an access rejection or publish elsewhere.
- Preserve every original input and downloaded source. Make corrections only
  in separate derivatives. Do not delete local datasets, archives or caches as
  a way to make Git clean. `.gitignore` controls publication, not preservation.
- Keep credentials, `.env`, private keys, tokens and account state out of Git.
  `.env.example` is the permitted configuration template. Inspect staged paths
  and diffs before committing; never add ignored credentials or bulk data with
  `git add -f`.
- Follow the tracked-data policy in `docs/GITHUB_WORKFLOW.md`. Native DTM and
  pluvial rasters, generated SQLite indexes, national cadastral source batches,
  bulk geometry, dependency trees, archives and rendering caches remain local.
  Small real rainfall inputs, source code, provenance and the permitted legacy
  vector/point inputs are intentional repository contents. No tracked file may
  reach GitHub's 100 MiB hard limit; use a separately agreed data distribution
  method rather than adding large originals to ordinary Git history.
- Preserve the distinction between original data, display derivatives and
  scientific analysis. Never fabricate terrain, infer building heights from
  floor counts, substitute an older pilot for the Digital Twin, or describe
  relative screening as validated flood probability/depth/damage.
- Run checks appropriate to the change. The complete restored-data baseline is
  `python -m pytest tests -q`, `pnpm test`, and `pnpm build`. Tests requiring
  excluded local data need the real matching snapshot; do not fabricate inputs
  or weaken verification to make a fresh clone appear fully validated. Explain
  any unavailable-data limit and run the independent checks that remain useful.

See `README.md` and `docs/GITHUB_WORKFLOW.md` for installation, data restoration,
source attribution, and the publication workflow. These instructions do not
authorize deployment of an externally reachable application or publication of
excluded datasets.
