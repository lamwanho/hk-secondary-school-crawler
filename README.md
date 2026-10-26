# Hong Kong secondary school crawler

Public factual school directory and independent admissions-notice discovery for local mainstream day secondary schools in Hong Kong.

The school directory was reconciled on 26 October 2026 using the Education Bureau's official School Location and Information bulk directory, plus factual fields from CHSC Secondary School Profiles 2025/26. It contains 478 registered school identities across 18 districts. See [ROSTER.md](ROSTER.md) and the [coverage ledger](docs/data/coverage.json) for source dates, section merges, exclusions and borderline classifications.

The scope includes ordinary government, aided, caput, DSS and registered local-private day secondary schools. It excludes EDB international/ESF categories, special schools, evening sections and education service centres. A school's name or curriculum does not override the publisher's category: local private independent schools offering IB/IAL are included where the directory classifies them as local-private. Directory inclusion does not establish S1 intake, an admissions event, a band estimate or a currently available booking.

## Public feed

The existing Study website reads these files directly. No access to a private repository is required:

- [School facts and reviewed events](https://raw.githubusercontent.com/lamwanho/hk-secondary-school-crawler/main/docs/data/pilot.json)
- [2027 planning estimates](https://raw.githubusercontent.com/lamwanho/hk-secondary-school-crawler/main/docs/data/forecasts.json)
- [Source-check results and candidate announcements](https://raw.githubusercontent.com/lamwanho/hk-secondary-school-crawler/main/docs/data/monitor.json)
- [Directory coverage and exclusions](https://raw.githubusercontent.com/lamwanho/hk-secondary-school-crawler/main/docs/data/coverage.json)

The 28 previously reviewed records and their 2024 onward event history are preserved. The other 450 schools initially have directory facts and explicit historical research gaps. Missing values are unknown, never invented. A successful crawler fetch is not manual verification of dates or registration availability. All detected notices require review before promotion to the reviewed events array.

## Schedule and zero GitHub charges

The public workflow runs daily at approximately 10:00 Hong Kong time, with a separate deeper run on Monday at 13:00 Hong Kong time. GitHub can delay scheduled jobs. Daily runs check a bounded set of key pages for every school, checkpoint after each 50-school batch and resume fairly after a deadline. Deeper runs rotate additional sources. Historical candidate evidence is preserved when a source changes or becomes inaccessible.

This repository uses standard `ubuntu-latest` runners in a public repository. GitHub documents these as free. The workflow has exact public-repository guards and a runtime visibility check; it has no paid runners, caches, artifact uploads, AI APIs, proxies, private-repository tokens or Vercel credentials. It writes only its own public data. The feed is served from raw GitHub files, so no Pages deployment or build artifact is required. This configuration does not consume paid private Actions minutes. It does not change billing or usage of unrelated repositories.

References: [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).

## Run locally

Python 3.12 or later:

```sh
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -v
python scripts/school-roster.py
python scripts/school-forecasts.py --input docs/data/pilot.json --output docs/data/forecasts.json --target-year 2027
python scripts/run-daily.py --mode daily
```

The roster build uses sanitized factual snapshots in `seed/`; it does not perform hundreds of school requests. The directory's publisher snapshot date is retained only if the publisher supplies one; retrieval date is separate. Directory updates should be reconciled against the official monthly source before replacing the sanitized source snapshot. Reviewed school facts and overrides remain explicit.

School websites are checked independently of CHSC participation. Confirmed official social sources are attempted where publicly readable; login gates, robots restrictions, errors and missing websites stay visible. The crawler does not bypass access controls, register for events or send messages. It stores only short excerpts, source URLs, hashes and access metadata, not full school pages, posters or PDF documents. Publisher material remains subject to its source terms.

See [operations](docs/OPERATIONS.md) for limits, resumption, retention and failure handling. No private Study application files or private Git history are included in this repository.
