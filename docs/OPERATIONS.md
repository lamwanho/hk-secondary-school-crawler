# Public collector operations

The collector reads `docs/data/pilot.json` and writes discovery evidence to
`docs/data/monitor.json`. It never changes the roster, verified events, fees,
school bands or forecasts. Candidate notices and date mentions remain
`review_required`. A date string in an admissions notice can describe a past
event or the academic entry year; it is not an automatically verified event.

## Schedule and zero-charge boundary

Only the PUBLIC repository `lamwanho/hk-secondary-school-crawler` runs the
workflow. Both jobs check the exact repository name and the event's public
visibility before allocating a runner, then confirm `.private == false` using
the GitHub API before collection and publication. Making the repository private
skips both jobs. No other repository is read or changed.

- Daily job: 02:00 UTC (10:00 Hong Kong), all roster schools,
  four key pages per school, four workers, 75 minutes of collection.
- Monday deeper job: 05:00 UTC (Monday 13:00 Hong Kong), twelve pages per school,
  four workers, 45 minutes. The historical endpoint reserved slot rotates by its
  last actual check time. This is a separate job and budget.
- `workflow_dispatch` accepts `daily` or `deep` for a manual run.

Both jobs use standard `ubuntu-latest`, not larger or custom runners. Public
standard GitHub-hosted runners incur no Actions minute charge under GitHub's
current public-repository policy. No cache, artifact upload, paid service,
AI API, Pages deployment, external dispatch, PAT or repository secret is used.
The built-in `GITHUB_TOKEN` has only `contents: write`, for committing the three
monitor output paths. Collection budgets sum to at most 120 minutes on the
weekly deeper-scan day. Job limits include an extra ten minutes for setup and
publishing. Scheduled runs may be delayed by GitHub; these times are targets.

The public raw feed is
`https://raw.githubusercontent.com/lamwanho/hk-secondary-school-crawler/main/docs/data/monitor.json`.
Publishing makes one data commit at the end of each collection job. No web build
is needed. Only `monitor.json`, `monitor-state.json` and `monitor-history/` are
staged; the roster and website code cannot be included in that data commit.

## Batching, deadlines and truthful coverage

`scripts/run-daily.py` processes sequential batches of at most 50 schools with
four workers. It atomically checkpoints the current evidence and a small resume
cursor after every batch. A completed run creates one final history snapshot.
The next run starts after the last actually attempted school; a slow prefix
cannot repeatedly starve the end of the roster. Daily and deeper cursors are
independent. A cancelled run can publish its latest complete batch checkpoint
when the runner reaches the final `always()` publication step. If the runner is
forcibly terminated before publication, the next run uses the last committed
checkpoint; there is no external paid state store.

Every roster school has an output row. `summary.schools_total` is the directory
count; `summary.schools_checked` counts schools with at least one source attempt
in this run. `schools_failed` counts attempted schools without a successful
source, `schools_deferred` counts eligible schools with no attempt, and
`schools_missing_website` counts rows lacking a valid website independently.
Rows retained from earlier runs retain their original per-school `checked_at`;
an untouched school never receives the run's new timestamp. Source counts also
separate attempted, failed and deferred endpoints. `run_status` can be `ok`,
`partial`, `failed` or `deferred`; a zero process exit means evidence was saved,
not that every website was accessible.

Daily checks favor the homepage, confirmed general/admissions social accounts,
stable admissions or current notice endpoints, and newly visible relevant
links. Older dated URLs wait for the deeper scan. Relevant numeric URLs can be
discovered without descriptive paths. Previously discovered sources rotate by
their last actual check time, including when the homepage returns HTTP 304.
Each successful body records its current notice keys. HTTP 304 refreshes only
those current candidates; archived notices retain their actual last-seen date.
Each school stores at most 40 active source endpoints. Each page contributes at
most 30 short candidate notices; earlier candidates are retained and deduplicated
by URL and title rather than erased when a live page removes them. This retains
2024 onward historical evidence separately from verified events and forecasts.

## Politeness and failure handling

Requests use an identifiable public-repository user agent, an eight-second
socket timeout and at most one retry for transport/5xx errors. Each host is
serialized across workers, with a 250 ms request delay. `robots.txt` is checked
once per origin. HTTP 401, 403 and 429 stop further requests to that host during
the run. There is no login, cookie injection, CAPTCHA bypass or browser
impersonation. Cross-host redirects are rejected. The global deadline stops
new page fetches; an in-flight socket operation can finish after the deadline.

Only confirmed general/admissions social accounts are checked; sports,
departmental and unconfirmed profiles are excluded. A login shell or inaccessible
profile is `social_unavailable`, not a successful post check. CHSC availability
does not gate independent website or confirmed social checks. Missing or blocked
sources retain their last good hashes, timestamps and historical notices.
HTML containing only scripts, markup or a page title is `no_extractable_text`;
it cannot replace last good evidence. A readable school welcome page with no
admissions notice can still be a successful source check.

Responses are capped at 3 MiB, PDF extraction at twelve pages and 60,000
characters. Full PDF/HTML bodies are not saved. Only hashes, conditional request
metadata, short titles/snippets, dates-as-mentioned and source URLs persist.
No OCR or unbounded attachment crawl runs. The repository keeps the latest
30 timestamped monitor snapshots; older committed snapshots remain in Git history.

## Local operation and checks

From the repository root, with Python 3.12:

```sh
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -v
python scripts/run-daily.py --mode daily --batch-size 50 --workers 4 --timeout 8 --max-seconds 4500
python scripts/run-daily.py --mode deep --max-seconds 2700
```

For a small explicit check, repeated `--school` flags preserve other existing
school rows. The standalone diagnostic CLI has its own short run budget:

```sh
python scripts/school-monitor.py --school SCHOOL_ID --school SECOND_ID --max-pages 4 --workers 2 --timeout 8 --max-seconds 120
python scripts/school-forecasts.py --input docs/data/pilot.json --output docs/data/forecasts.json --target-year 2027
```

`run-daily.py` also accepts `--input`, `--output`, `--state`, `--workers` (1–6),
`--batch-size` (1–50), `--timeout` (2–10) and `--max-seconds` (1–5400). Custom
outputs permit isolated checks. Forecast generation remains a separate explicit
operation and uses only cited dated event history; monitor discovery candidates
cannot turn into forecast samples automatically.

When a run fails, inspect its Actions batch summaries and the per-source error.
Fix a confirmed school URL in the roster's source-building process, or wait for
the next rotating run when a host is temporarily unavailable. Do not classify
access failures as evidence that a school has no open day. Git push conflicts
fail visibly and preserve the remote data; there is no force push.
