# Secondary-school roster and evidence coverage

The published roster contains **478 registered school identities in all 18 districts**, checked on **26 October 2026**. It combines the EDB monthly school directory with 441 factual CHSC 2025/26 profile records and the 28 previously reviewed school histories. There are **60 historical event records (57 dated)** across those 28 schools. The remaining **450 schools have directory coverage; historical events have not yet been researched**. They must never be shown as schools that held no event.

## Scope and school identity

Include ordinary Government, Aided, Caput and DSS secondary schools, and EDB-registered local-private secondary **day** sections. A private school remains in scope when it offers IB, IGCSE or IAL. Include upper-form schools as secondary schools; their inclusion does not imply an S1 intake.

Exclude EDB international-school categories, ESF-operated schools (including private independent Renaissance College and Discovery College), special schools, evening sections and the three education service centres. Tutorial-only and non-formal courses are not school identities in this roster. A registered formal secondary day school is retained even when its operator also provides tutoring; this applies to Beacon's day-school registrations.

School identity uses the first six digits of the EDB school number, which the [official school lists](https://www.edb.gov.hk/en/student-parents/sch-info/sch-search/schlist-by-district/school-list-i.html) identify separately from Location ID. The build also requires an exact normalized school name before merging sections under one registration. Different registrations are not merged by a shared website, address or similar name. Every full section number and Chinese campus address remains in `directory_source.campuses`; `coverage.json` records every campus merge. Conflicting names under one registration abort the build for review.

| Accounting step | Count |
|---|---:|
| All levels in the official EDB JSON | 3,496 |
| Secondary section rows retained as sanitized input | 647 |
| Exact duplicate secondary source rows removed | 15 |
| Excluded secondary section records | 138 |
| Included secondary sections | 494 |
| Section/campus consolidation reduction | 16 |
| Included school identities | 478 |

| Official funding category | Included school identities |
|---|---:|
| Government | 29 |
| Aided | 355 |
| Caput | 2 |
| DSS | 57 |
| Private | 35 |

The 443 funded ordinary schools are distinct from the official 446 count including the Arts & Technology Education Centre, Ho Koon Nature Education cum Astronomical Centre and Caritas Chan Chun Ha Field Studies Centre. EDB's [statistical definition](https://www.edb.gov.hk/attachment/en/about-edb/publications-stat/figures/Enrol_2024.pdf) expressly includes those centres in school counts. Neither 446 nor the broader 2025/26 all-sector 513 count is a forced target for this roster.

| Exclusion reason | Unique registrations | Section records |
|---|---:|---:|
| Special schools | 62 | 82 |
| International-school category | 26 | 30 |
| ESF including Discovery/Renaissance | 8 | 9 |
| Evening sections | 8 | 13 |
| Education service centres | 3 | 4 |

An evening exclusion may share a registration with an included day school. These unique exclusion counts therefore must not be added to included identity counts as if they were disjoint schools. Full excluded names, numbers, sessions and reasons are public in `docs/data/coverage.json`.

## Private schools and classification ambiguity

The [EDB Private Independent School list](https://internationalschools.edb.gov.hk/en/schools/pis.html) includes ICQM, ICS, Choi Kai Yau, ISF, VSA and Yew Chung Secondary. These six private schools are included. ESF Discovery and Renaissance are excluded by the agreed ESF scope. “International” appearing in a name is not itself an exclusion rule.

Invictus and Wycombe Abbey are EDB “Other Private Secondary Schools” in the [official voluntary formal-curriculum list](https://www.edb.gov.hk/attachment/en/edu-system/primary-secondary/applicable-to-primary-secondary/private-sch-formal-curriculum/Other%20Private%20Secondary%20Schools_E.pdf), dated 15 October 2026. The list is voluntary and expressly non-exhaustive; absence is not an exclusion criterion.

Both Stamford registrations are categorized as private in the EDB directory, although their public branding refers to international education. They remain included under the rule that official category controls classification. This ambiguity is visible in the classification ledger. It is not silently resolved from a school name or curriculum. The same ledger explains each private/PIS inclusion and supplies source URLs.

## Source register

Contains information provided by the Education Bureau, the Committee on Home-School Co-operation, the Government of the Hong Kong SAR and DATA.GOV.HK. The [DATA.GOV.HK terms](https://data.gov.hk/en/terms-and-conditions) permit free reuse with source/ownership attribution and provide data as supplied, without a completeness or timeliness guarantee.

| Source | What is retained | Access on 26 October 2026 | Date/cadence limitation |
|---|---|---|---|
| [EDB School Location and Information via DATA.GOV.HK](https://data.gov.hk/en-data/dataset/hk-edb-schinfo-school-location-and-information) → [official bulk JSON](https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.json) | Public secondary registration numbers, names, categories, Chinese addresses, districts, gender, sessions, funding, website URLs | HTTP 200; 3,496 parsed source rows, 647 secondary rows | Monthly. The payload has no internal effective-date field; retrieval date is not its issue date. |
| [CHSC official 2025/26 CSV](https://www.chsc.hk/datagovhk/ssp_2025_2026_en.csv) | Only school name, district, website, gender, type, published S1 fee and S1 class count | HTTP 200; 441 parsed profiles, all 441 matched to an included identity | 2025/26 academic year. Class counts are not intake places. |
| `seed/verified-schools.json` | The 28 reviewed histories and their exact cited fees, intakes, outcomes, bands and social evidence | Local reviewed input | Bounded research, not continuous monitoring. |

The HTTP identity used for the two successful downloads was `school-roster-collector/1.0 (python-urllib)`, with `Accept: application/json` for EDB and `Accept: text/csv` for CHSC. No cookies, credentials, login or refusal bypass was used. A previous PowerShell CHSC download had stalled; the bounded Python download succeeded. A first Python attempt lacked the optional `requests` package and made no network call. The successful downloader used Python's standard library. The web reader could not display the entire 4.3 MB EDB JSON due to its display-size limit; that was not an HTTP denial.

Only sanitized factual inputs are committed. CHSC school missions, staff profiles, full admissions prose and other long copyrighted material are omitted. The bulk CHSC CSV has no dedicated historical event date feed. No event dates were inferred from its academic-year headings or prose. Three English-only values in EDB's Chinese-name field are retained without inventing Chinese names.

Six website URLs are blank in EDB. All six were subsequently matched to directly read official school pages, recorded in `seed/website-overrides.json`: Anantara, Anchors, Spanish School, Speater, Stamford West Kowloon and Zhongshan Whampoa. Anantara and Speater print their exact EDB registration numbers. Spanish School prints its registration number and a registered campus address. Anchors identifies its Junior Secondary section and Ko Po Path campus; Stamford identifies its West Kowloon school and Imperial Cullinan address; Zhongshan Whampoa gives the matching Hong Kong name and Tat Chee Avenue address. Top-level website links now have **zero missing URLs**, while all six original `directory_source.website` values stay null. Each correction has separate `website_provenance` with the proof URL, checked date, verification scope and identity notes. These identity checks do not count as historical event research or social-account verification.

A lead for a later event review: on 26 October 2026 the [official Zhongshan Whampoa homepage](https://www.zwa.com.hk/) displayed “2027–2028 S1 Admission Info Session & Open Day” and “31 Oct 2026 (Sat), 2:00–4:30 PM”, alongside the matching Tat Chee Avenue address. Its [linked event page](https://www.zwa.com.hk/en/node/200) returned a reader cache miss and has not been independently inspected. This lead was not added to normalized event history or forecasts during the website-only follow-up.

## Reviewed evidence and unknown fields

The merge preserves every existing field of all 28 reviewed school records, including DBS and St Margaret's reference-band corrections. Seed IDs remain stable. Official directory values are added under `directory_source` instead of replacing a reviewed field; differences are recorded in `coverage.json`. Matching uses an exact Chinese/normalized English name or a unique official website host, with every match method recorded. DBS and DGS remain separate and primary sections never enter this secondary input.

New IDs use `edb-` followed by the six-digit official registration number. New school fields for band, intake, outcomes and event history remain null/empty. Each new 2024–2026 school-year coverage cell is `not_researched`. A CHSC dash, range or conditional tuition is not converted to zero. A single numeric S1 tuition value can be copied with its 2025/26 provenance. No timetable, event date, registration opening or interview date is invented.

`docs/data/forecasts.json` is a separate 2027 planning dataset generated from actual retained historical events. It has one row for every roster school. Schools without comparable dated history have unknown planning windows. A roster row does not activate monitoring or certify that its website or social accounts were independently read.

## Rebuild and check

Run with Python 3 from the repository root:

```powershell
python -Xutf8 scripts/school-roster.py
python -Xutf8 scripts/school-forecasts.py --input docs/data/pilot.json --output docs/data/forecasts.json --generated-at 2026-10-26
python -Xutf8 -m unittest discover -s tests
```

The roster build is offline and deterministic from the three core seed inputs and optional `seed/website-overrides.json`. It aborts on unmatched reviewed schools, duplicate reviewed identity matches, invalid official numbers, conflicting registration names, or website overrides without same-site official identity proof metadata. An override fills a blank new-school website and never replaces a reviewed school field or an EDB source field. Refresh source snapshots deliberately; do not infer a current publisher date or silently replace reviewed evidence.
