# Profile card generator

Regenerates the two stat cards shown on the profile README:

- `profile/stats.svg` — stars, commits, PRs, issues, repos contributed to
- `profile/top-langs.svg` — most used languages (donut)

Both are plain SVG in the `tokyonight` palette. They are committed to the repo,
so GitHub serves them directly in the README.

## Why not the public github-readme-stats service?

That service can only see **public repos you own**. This generator reads **every
repo you have authored commits in**, including private and organisation repos, so
the language card reflects your whole body of work (C, Python, Kotlin, TypeScript,
C++, Go, OCaml, Rust, ...) rather than just the public C/TeX academic repos.

## Run it locally

Needs Python 3 (standard library only) and a GitHub token that can see your
private/org repos.

```bash
# Uses your gh login if GH_TOKEN/GITHUB_TOKEN are not set:
python3 scripts/generate_profile_cards.py --out profile

# Or with an explicit PAT (classic, scopes: repo + read:org):
GH_TOKEN=ghp_xxx python3 scripts/generate_profile_cards.py --out profile
```

It prints the numbers it found and writes the two SVGs. Commit them to update the
profile.

## Run it from the homelab (auto-refresh)

`docker/` holds a one-shot container that clones this repo, regenerates the cards,
and pushes any change. Wire it into your homelab compose stack, or run standalone:

```bash
cd docker
echo 'GH_TOKEN=ghp_your_pat_with_repo_and_read_org' > .env   # gitignored
docker compose up --build
```

On `up` it regenerates and pushes, then exits. Set `REFRESH_INTERVAL` (seconds)
in the compose file to keep it running and refresh on a timer instead.

## Tuning (top of `generate_profile_cards.py`)

- `EXCLUDE_LANGS` — languages hidden from the card. Defaults to `{"TeX"}`.
- `EXCLUDE_REPOS` — repos left out of the language mix entirely. Empty by
  default so the card shows everything.
- `TOP_N` — how many languages before the rest roll into "Other" (default 12).

### Gotcha: language bytes are whole-repo, not your lines

Percentages come from GitHub's per-repo language byte counts, summed over every
repo you've committed to. A repo counts its **entire** language makeup, not just
the parts you wrote. So a large monorepo you touched contributes all of its
languages (e.g. Go / Starlark / HCL from build + infra you may not have authored).
If a big repo skews the mix, add it to `EXCLUDE_REPOS`. Measuring only your own
lines would require cloning and running per-author line analysis, which this
script deliberately avoids to stay fast and dependency-free.
