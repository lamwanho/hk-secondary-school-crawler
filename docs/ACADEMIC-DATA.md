# Academic reference import — 26 October 2026

The owner supplied three AI-assisted compilation files. They contain public school facts and secondary-source estimates. They are imported as attributed reference claims, not as proof that 439 school websites have been checked. The input filenames and SHA-256 checksums are recorded in `seed/academic-reference-2026.json`; private filesystem locations and complete copied source documents are not published.

## Reconciliation

- All 439 CSV records uniquely match existing Chinese/English school names in the 478-school roster. No school is added or removed.
- The banding Markdown and CSV agree on all 439 identities, selected bands and headline percentages. The detail Markdown also matches all 439 identities.
- Current reference bands increase from 28 to 425. Source years before 2024 stay as historical reference and do not fill current band filters. Names, original band ranges, source-reported accuracy labels and source selection explanations are retained. Source-reported accuracy is not our verification assessment.
- The owner's Band 1B corrections for Diocesan Boys' School and St. Margaret's remain in force. The imported conflicting estimates remain visible in school details. Four imports differ from an existing reference band; prior references are retained when superseded.
- The CSV has 171 degree-entry threshold claims and 99 ambiguous combined degree/subdegree headline measures. The latter are retained only in the definition-review section, never used as university admission rates or sorting keys.
- There are 279 schools with imported progression claims and **263** with at least one school-specific subject statistic. The supplied Markdown's comment says 199; this summary was not adopted because a count of the actual nonempty school-statistic cells gives 263. Hong Kong benchmark columns are excluded from that count and stored separately.
- Actual source cohorts span 2012–2026. A file named 2026 does not turn an older result into a 2026 result. The band estimate year, result cohort and event year remain independent.

## Verification boundaries and spot checks

The [CNEC Christian College reference page](https://dse.bigexam.hk/en/ssp/school/432) was read in an ordinary browser. It confirms the 2025 Band 1B–1A estimate and approximately 88.1% degree-entry threshold, along with some subject and progression figures. This checks the secondary publisher, not every underlying school claim. Imported records therefore keep `secondary_compilation_unverified`. Other figures in the supplied compilation were not promoted merely because one sample matches.

The [Tseung Kwan O Government Secondary School results page](https://www.tkogss.edu.hk/en/public-exam-results) was directly read. Its 2026 section states 70% at 332A22 and 63.6% at 332A33. Those two exact measures are separately retained in `seed/school-academic-verifications.json` with `school_page_verified`; the compilation's older 2025 mixed measure remains separate. Neither percentage is an admission, offer or matriculation rate.

The [DGS homepage](https://www.dgs.edu.hk/) contains public 2026 DSE and GCE A-level result notices, so the compilation's broad statement that DGS does not publish DSE statistics is not used as an established fact. Its imported numeric details still need confirmation against the corresponding original school publication. Reading a congratulatory notice does not verify a cohort-wide rate.

Approximation/comparison wording such as `大約`, `接近` and `超過` is retained alongside the numeric sorting value. Different progression measures and denominators are not pooled or averaged. DSE-only input never creates an IB/IAL result. No event, booking, replay, intake, fee, address or official-social evidence is changed by this import.

## Rebuild

`python scripts/school-roster.py` reapplies the sanitized academic seed offline after the EDB/CHSC identity build. The overlay is idempotent and rejects unknown or duplicate identities. Original reviewed evidence remains in `seed/verified-schools.json`. To regenerate the academic seed from the owner's original files, run `scripts/school-academics.py --csv <csv> --banding-notes <md> --detail <detail-md>`, then rebuild the roster and run tests.

The existing Study UI reads the public feed and has a matching local fallback. Table summaries, details and CSV keep verification status, years, definitions and qualifiers. Original entry-eligibility records are displayed separately from progression as well. The separate historical-performance page remains deferred. Crawler schedules, source budgets, public free-runner guards and private-repository Actions settings are unchanged.
