# Water Hackathon repository access and review receipt

Requested source: [users/mironikolov_vt/water_hackathon](https://earthengine.googlesource.com/users/mironikolov_vt/water_hackathon).

Checked 24 October 2026. The first access check was approximately 20:43 Europe/Sofia; a subsequent normal Git-helper retry is recorded below. Neither clone completed, so no repository code, README, dataset definitions or commit was available for inspection. No code from this repository has been executed or incorporated into the app.

## First attempt: credential-free public read

Run from `C:\Users\Yoan\Documents\Codex\2026-10-24\hp` in PowerShell:

```powershell
$env:GIT_TERMINAL_PROMPT='0'
git -c credential.helper= clone --no-recurse-submodules 'https://earthengine.googlesource.com/users/mironikolov_vt/water_hackathon' 'work/water_hackathon'
```

Git 2.53.0.windows.3 returned exit code 1:

```text
Cloning into 'work/water_hackathon'...
fatal: could not read Username for 'https://earthengine.googlesource.com': terminal prompts disabled
```

A separate unauthenticated HTTP GET to the normal Git discovery endpoint returned **HTTP 401**:

```text
https://earthengine.googlesource.com/users/mironikolov_vt/water_hackathon/info/refs?service=git-upload-pack
```

`work/water_hackathon` was absent after Git's failed clone. Credential helpers and interactive prompts were disabled for this first attempt. No stored account credentials were read for this attempt. The HTTP result alone does not establish whether the repository is private, the URL is incorrect or unauthenticated access to that service is unavailable.

## Second attempt: normal configured Git credential helper

The user's explicit clone instruction was also tried with the normal existing Git helper enabled, while suppressing login windows and interactive prompts. No credential-store inspection or credential output was requested.

```powershell
$env:GIT_TERMINAL_PROMPT='0'
$env:GCM_INTERACTIVE='never'
git clone 'https://earthengine.googlesource.com/users/mironikolov_vt/water_hackathon' 'work/water_hackathon'
```

Git again returned exit code 1:

```text
Cloning into 'work/water_hackathon'...
fatal: Could not load file or assembly 'System.Configuration, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a' or one of its dependencies. The system cannot find the file specified.
fatal: could not read Username for 'https://earthengine.googlesource.com': terminal prompts disabled
```

This retry reveals a separate local dependency failure in the configured credential helper. It does not establish whether any existing account has access to the repository. No login UI or account provisioning was performed; no Earth Engine credentials, authenticated SDK or blocked browser endpoint was used.

## Review status

| Requested check | Result |
| --- | --- |
| Exact commit | Unavailable; no refs or object database retrieved |
| README and JavaScript files | Unavailable |
| Scientific model, equations and units | Not reviewed; contents inaccessible |
| Dataset IDs, availability and native resolution | Not reviewed |
| Rainfall aggregation and intensity conversions | Not reviewed |
| Flood calibration or validation evidence | Not reviewed |
| Changes incorporated into Sofia app | None |

No finding about this repository's scientific quality, bugs or compatibility is justified without its contents. The current Sofia screening method therefore retains its existing, separately documented provenance and limitations.

## Useful next input and review scope

An exported repository ZIP or publicly readable source mirror would allow the review to continue without account access. Once the actual source is available, check its terrain conditioning, contributing-area units, rainfall units and timesteps, land-cover resolution, drainage assumptions, masking and NoData, infrastructure exposure grain, and independent flood validation. Any calibrated event data or transparent physical runoff/hydraulic method may improve the present terrain-only screen, but that benefit cannot yet be attributed to this inaccessible repository.
