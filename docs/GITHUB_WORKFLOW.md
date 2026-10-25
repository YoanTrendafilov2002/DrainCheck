# DrainCheck source repository and future updates

The user requested publication of this app and future tested updates to
[YoanTrendafilov2002/DrainCheck](https://github.com/YoanTrendafilov2002/DrainCheck).
The configured SSH remote is `git@github.com:YoanTrendafilov2002/DrainCheck.git`
and the shared branch is `main`. `AGENTS.md` records this continuing instruction.
Publishing source code does not deploy the local API or publish ignored data.
Initial publication uses the connected GitHub tools, whose repository write
access has been verified; the SSH origin is recorded even though this computer
has no configured SSH key. Future tested updates may publish through that
authorized GitHub connection and verify the resulting remote commit without
requiring local SSH setup.

## What belongs in Git

Track the application, scripts, tests, dependency lockfiles, configuration
template, source documentation and small verification receipts/screenshots.
Retain the complete 201-value Earth Engine quantile snapshot, current canonical
metadata, and actual small rainfall COGs, numeric snapshots and all 55 stations.
These rainfall files total approximately **0.501 MiB** and use original native
values/masks. OPERA and Weather Underground attribution and the upstream
verification/reuse limitations remain in the rainfall source documentation.

The real decoded legacy route/green/point inputs total **58.16 MiB**, with small
prepared route/green partitions adding **4.97 MiB**. The repository stores the
unchanged green-area original as a lossless **14.1 MB (13.44 MiB) gzip bundle**
under `data/source_bundles/`, plus the other small raw inputs and partitions.
The 53,164,382-byte original GeoJSON remains intact locally and is ignored by
Git. The first API upload of that raw file was rejected for input size; gzip
changes its storage representation, not its geometry, attributes or bytes after
decoding. A fresh checkout restores it before building the vector index.
GitHub [warns about files above 50 MiB and blocks files above 100 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
Do not add any file at that limit or above it.

`scripts/restore_source_bundles.py` uses only Python's standard library, with no
login or network access. It verifies compressed size/SHA256, gzip decoding/CRC,
and the original decoded size/SHA256 from `data/source_bundles/manifest.json`.
An existing matching original is left untouched; a conflicting original causes
a failure without overwrite. A missing original is installed atomically only
after its complete temporary copy passes validation. The destination is a fixed
path within this application, rather than an archive-controlled output path.

Keep the following files local and ignored. Ignoring them never deletes them:

| Local material | Why it is separate |
|---|---|
| Native municipal 1 m DTM and other large rasters | Large immutable scientific input, restored from a verified source |
| Raw 5 m terrain factors, score/land-screening rasters | Large verified scientific inputs/derivatives; no substitute terrain |
| SQLite spatial/cadastral indexes, rendered tiles and local colour fits | Rebuildable local caches |
| AGKK original gzip batches, full cadastral GeoJSON and archival GeoJSON | Bulk acquired source/derivative data; retain exact provenance and rights limitations |
| Original handoff ZIPs, duplicate upload ZIPs and large source reports | Preserved local originals; referenced by receipts and source guides |
| Decoded 53.16 MB green-area GeoJSON | Restored byte-for-byte from the permitted lossless source bundle |
| Unlicensed research geometry | A public download alone does not establish publication rights |
| `.env`, keys, tokens, credentials, virtual environments and `node_modules` | Local configuration, secrets or reproducible dependencies |
| `dist/`, coverage files, test runner caches and logs | Generated build/verification output |

Canonical small metadata under `data/cache/` is selectively tracked for audit;
it is not proof that the ignored binary files are present on a new computer.
The API verifies actual local sources and reports unavailable data explicitly.
Do not overwrite originals or add an ignored file forcibly to bypass this policy.

## Fresh checkout

Use the lockfiles rather than copying the current machine's dependency tree:

```powershell
git clone git@github.com:YoanTrendafilov2002/DrainCheck.git
Set-Location -LiteralPath DrainCheck
python -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-lock.txt
Copy-Item -LiteralPath '.env.example' -Destination '.env'
pnpm install --frozen-lockfile
pnpm build
& '.venv/Scripts/python.exe' scripts/restore_source_bundles.py
& '.venv/Scripts/python.exe' scripts/prepare_data.py
& '.venv/Scripts/python.exe' scripts/prepare_rainfall_cache.py
& '.venv/Scripts/python.exe' scripts/serve.py
```

The included vectors and rainfall are real data. Elevation and 5 m pluvial
screening require the separately restored native datasets; their absence must
remain visible. The generated `dist/` is rebuilt by `pnpm build`, so it is not
expected to exist immediately after cloning.

Restore the verified DTM to `data/external/sofia_dtm_2024_1m_gee.tif`, or point
`SOFIA_DTM_PATH` in the local `.env` to its existing location. The exact grid,
NoData, source identity and preserved vertical datum are specified in the README
and provenance. A screenshot, resampled terrain or unrelated DEM is rejected.
For the existing pluvial result, restore the matching verified local raster and
its source receipts; see the pluvial preparation script and source guides.
After restoring the native DTM, run `scripts/prepare_data.py` again and then
`scripts/restore_reference_scale.py` with the same Python environment. The curve
restorer deliberately requires the verified actual DTM; it is not a prerequisite
for running the vector/rainfall app without terrain.

The source-bundle verification is recorded separately in
`test-artifacts/source_bundle_verification.json`; those restoration checks are
not added to the unchanged 220-test application baseline.

Restore AGKK buildings by copying the matching preserved source directory and
metadata from the existing installation, then rebuild its independent index,
or acquire a new public-service snapshot explicitly:

```powershell
& '.venv/Scripts/python.exe' scripts/acquire_agkk_buildings.py
```

The live national service can change. A new acquisition is a new audited
snapshot, not a promise of byte-identical reproduction of the October 2026
snapshot. The initial count/ID list, all responses, checksums, scope and final
count must be verified again. Do not mix old metadata with new batches. Preserve
the AGKK access/usage terms in [the source notes](AGKK_CADASTRAL_BUILDINGS_SOURCES.md);
public query access is not a claim of unrestricted redistribution rights.

The municipal archival alternative is independently reproducible with
`scripts/acquire_cadastral_buildings.py`; it is not promoted into the national
layer. Full handoff verification scripts require restoring all 53 original
supplement files locally, including the large copies excluded from Git. Existing
original archives remain intact on this machine. Other source guides identify
the historical PDF/report downloads and mapped survey geometry.

## Publishing a tested update

1. Implement the requested work while preserving unrelated changes and originals.
2. Run meaningful targeted checks and the required build. With the full matching
   local data restored, the current baseline is **196 Python tests + 24 frontend
   tests (220 total)** and a passing production build. Data-dependent checks on
   an incomplete clone are not equivalent to that full baseline.
3. Review `git status --short`, `git diff`, staged paths, file sizes and the
   intended commit diff. Check that no credentials, native rasters, caches or
   unintended original datasets are staged.
4. Commit the intended files, then push the normal update to the configured
   remote. Keep this user's future-update instruction in force unless changed.

```text
git diff --check
git diff --cached --stat
git commit -m "Describe the verified application change"
git push origin main
```

Never use a force push, destructive history rewrite, branch deletion or original
file deletion as a shortcut. If authentication, an access rejection or a remote
change prevents publication, preserve the complete local work, state the actual
blocking result, and resolve it without bypassing security or claiming success.
