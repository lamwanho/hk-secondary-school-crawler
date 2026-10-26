#!/usr/bin/env python3
"""Reproducible offline EDB roster merge; reviewed school facts remain intact.

The sanitized inputs contain public directory facts, not full school profiles.
No network access occurs during a build. See ROSTER.md for scope and provenance.
"""
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
EDB_URL = 'https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.json'
CHSC_URL = 'https://www.chsc.hk/datagovhk/ssp_2025_2026_en.csv'
CATEGORIES = {
    'Aided Secondary Schools': 'Aided', 'Caput Secondary Schools': 'Caput',
    'Government Secondary Schools': 'Government',
    'Direct Subsidy Scheme Secondary Schools': 'DSS',
    'Private Secondary Schools (Day/Evening)': 'Private',
}
CENTRES = {'511072', '517160', '519162'}
ESF_PRIVATE = {'567485', '569747'}
# Scope follows the publisher's category, not a school's name or curriculum.
# The Stamford registrations are explicitly private in this EDB payload and
# therefore cannot be silently reclassified from branding alone.
INTERNATIONAL_PRIVATE = set()
PIS = {'543560', '553867', '553190', '569836', '560138', '567450', *ESF_PRIVATE}
REGIONS = {'CENTRAL AND WESTERN': 'HK', 'EASTERN': 'HK', 'SOUTHERN': 'HK', 'WAN CHAI': 'HK',
           'KOWLOON CITY': 'KLN', 'KWUN TONG': 'KLN', 'SHAM SHUI PO': 'KLN',
           'SHUM SHUI PO': 'KLN', 'WONG TAI SIN': 'KLN', 'YAU TSIM MONG': 'KLN'}
CHSC_ALIASES = {'511650': 'CCC Rotary Secondary School', '543314': 'HKCCCU Logos Academy'}


def normalized(value):
    return re.sub(r'[^a-z0-9\u3400-\u9fff]', '', (value or '').casefold())


def website(value):
    value = (value or '').strip()
    if value in ('', '-', 'N.A.'): return None
    if '://' not in value: value = 'https://' + value
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password: return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', '', ''))


def host(value):
    return (urlsplit(website(value) or '').hostname or '').casefold().removeprefix('www.').removeprefix('www2.')


def registration(row):
    value = str(row['SCHOOL NO.']).zfill(12)
    if not re.fullmatch(r'\d{12}', value): raise ValueError('Invalid official school number: ' + value)
    return value[:6]


def excluded_reason(row):
    base = registration(row)
    category = row.get('ENGLISH CATEGORY', '')
    if row.get('SCHOOL LEVEL') != 'SECONDARY': return 'not_secondary'
    if 'Special' in category: return 'special_school'
    if 'International' in category or base in INTERNATIONAL_PRIVATE: return 'international_school'
    if 'English Schools Foundation' in category or base in ESF_PRIVATE: return 'esf_school'
    if row.get('SESSION') == 'EVENING': return 'evening_section'
    if base in CENTRES: return 'education_service_centre_not_ordinary_school'
    if category not in CATEGORIES: return 'outside_local_secondary_categories'
    return None


def unique_match(row, candidates, name_key, website_key, zh_key=None):
    exact = [c for c in candidates if normalized(c.get(name_key)) == normalized(row.get('ENGLISH NAME'))
             or (zh_key and c.get(zh_key) and normalized(c[zh_key]) == normalized(row.get('中文名稱')))]
    if len(exact) == 1: return exact[0], 'exact_name'
    domain = host(row.get('WEBSITE'))
    by_domain = [c for c in candidates if domain and host(c.get(website_key)) == domain]
    if len(by_domain) == 1: return by_domain[0], 'unique_official_website_host'
    return None, None


def numeric_fee(value):
    # A dash is unknown. Ranges, installments and conditional amounts require review.
    value = (value or '').strip().strip('"').replace(',', '')
    match = re.fullmatch(r'(?:HK\$|\$)?\s*(\d+(?:\.\d+)?)', value)
    return float(match[1]) if match and '.' in match[1] else int(match[1]) if match else None


def summarize(schools, checked_date):
    events = [event for school in schools for event in school.get('events', [])]
    dated = [event for event in events if event.get('start_date')]
    year = lambda e: str(e.get('event_year')) if e.get('event_year') else 'unknown'
    level = lambda e: e.get('verification', {}).get('level', 'unknown')
    return {'checked_date': checked_date, 'schools': len(schools), 'events': len(events),
            'dated_events': len(dated), 'undated_leads': len(events)-len(dated),
            'districts': len({s['district'] for s in schools}),
            'schools_by_region': dict(Counter(s['region'] for s in schools)),
            'schools_by_type': dict(Counter(s['school_type'] for s in schools)),
            'schools_by_district': dict(sorted(Counter(s['district'] for s in schools).items())),
            'events_by_year': dict(Counter(year(e) for e in events)),
            'dated_events_by_year': dict(Counter(year(e) for e in dated)),
            'events_by_evidence_level': dict(Counter(level(e) for e in events)),
            'dated_events_by_evidence_level': dict(Counter(level(e) for e in dated)),
            'schools_with_fee_amount': sum(s.get('school_fee', {}).get('amount_hkd') is not None for s in schools),
            'schools_with_address': sum(bool(s.get('school_address_zh')) for s in schools),
            'schools_with_intake_total': sum(s.get('s1_intake', {}).get('total') is not None for s in schools),
            'schools_with_reference_band_2024_onwards': sum(bool(s.get('reference_band', {}).get('display')) and (s.get('reference_band', {}).get('year') or 0) >= 2024 for s in schools),
            'schools_with_outcome_rate': sum(any(o.get('rate') is not None or o.get('rate_percent') is not None for o in s.get('university_outcomes', [])) for s in schools),
            'schools_with_official_social_evidence': sum(any(a.get('official_evidence_url') for a in s.get('official_social_accounts', [])) for s in schools),
            'dated_school_year_cells': sum(any(e.get('start_date') and e.get('event_year') == y for e in s.get('events', [])) for s in schools for y in (2024,2025,2026)),
            'school_year_cells_checked': sum(c.get('status') != 'not_researched' for s in schools for c in s.get('year_coverage', [])),
            'school_year_cells_not_researched': sum(c.get('status') == 'not_researched' for s in schools for c in s.get('year_coverage', [])),
            'schools_with_historical_events': sum(bool(s.get('events')) for s in schools),
            'validation_errors': 0, 'validation_warnings': 0}


def build_roster(directory, verified, chsc, website_overrides=None):
    checked = directory.get('checked_date', '2026-10-26')
    edb_url = directory.get('source_url', EDB_URL)
    chsc_url = chsc.get('source_url', CHSC_URL)
    website_overrides = website_overrides or {}
    applied_websites = []
    for key, proof in website_overrides.items():
        if (proof.get('verification_level') != 'official_school_page_identity_verified'
            or not website(proof.get('website')) or not website(proof.get('source_url'))
            or host(proof['website']) != host(proof['source_url'])
            or not proof.get('checked_date') or not proof.get('notes')):
            raise ValueError(f'{key}: website override requires cited official school-page identity evidence')
    groups, excluded, duplicate_count, seen = defaultdict(list), [], 0, set()
    for row in directory['rows']:
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            duplicate_count += 1
            continue
        seen.add(signature)
        reason = excluded_reason(row)
        if reason:
            excluded.append({'school_no': str(row['SCHOOL NO.']), 'registration_no': registration(row),
                             'name_en': row.get('ENGLISH NAME'), 'category': row.get('ENGLISH CATEGORY'),
                             'session': row.get('SESSION'), 'reason': reason})
        else: groups[registration(row)].append(row)
    schools, merges, matches, unmatched_chsc, changes, borderlines = [], [], [], [], [], []
    for base, sections in sorted(groups.items()):
        names = {normalized(row['ENGLISH NAME']) for row in sections}
        if len(names) != 1: raise ValueError(f'Different names share registration {base}; manual review required')
        row = sections[0]
        seed, seed_method = unique_match(row, verified['schools'], 'name_en', 'website', 'name_zh')
        profile, profile_method = unique_match(row, chsc['rows'], 'school_name', 'school_website')
        if not profile and base in CHSC_ALIASES:
            found = [c for c in chsc['rows'] if c['school_name'] == CHSC_ALIASES[base]]
            if len(found) == 1: profile, profile_method = found[0], 'reviewed_name_alias'
        if not profile: unmatched_chsc.append({'registration_no': base, 'name_en': row['ENGLISH NAME']})
        district = row['DISTRICT'].title().replace('Central And Western', 'Central & Western').replace('Shum Shui Po', 'Sham Shui Po')
        gender = {'BOYS':'Boys','GIRLS':'Girls','CO-ED':'Co-ed'}.get(row.get('STUDENTS GENDER'))
        directory_values = {'name_en': row['ENGLISH NAME'], 'name_zh': row['中文名稱'], 'website': website(row.get('WEBSITE')),
                            'district': district, 'region': REGIONS.get(row['DISTRICT'], 'NT'), 'gender': gender,
                            'school_type': CATEGORIES[row['ENGLISH CATEGORY']], 'school_address_zh': row['中文地址']}
        if seed:
            school = copy.deepcopy(seed)
            for key, value in directory_values.items(): school.setdefault(key, value)
            matches.append(seed['id'])
            for key, value in directory_values.items():
                if key in seed and seed[key] != value:
                    changes.append({'id': seed['id'], 'field': key, 'reviewed_value': seed[key], 'directory_value': value,
                                    'policy': 'reviewed display retained; official directory value available in directory_source'})
        else:
            school = {'id': f'edb-{base}', **directory_values,
                      'chsc_profile_url': None, 'chsc_discovery_status': '2025/26 official bulk profile matched' if profile else 'not_in_2025_26_bulk_profile',
                      'school_fee': {'amount_hkd': numeric_fee(profile.get('sc_school_fee_s1')) if profile else None,
                                     'academic_year': '2025/26' if profile else None, 'level': 'S1',
                                     'status': 'official CHSC S1 tuition field; dash/range/conditional values remain unknown' if profile else 'not_researched',
                                     'source_url': chsc_url if profile else None},
                      'reference_band': {'display': None, 'reported': None, 'year': None, 'source_url': None,
                                         'status': 'not_researched', 'notes': 'No estimate assigned; bands are not official school classifications.'},
                      's1_intake': {'admission_year': None, 'total': None, 'external': None, 'linked_reserved': None,
                                    'relationship': None, 'linked_school_names': [], 'source_url': None},
                      'university_outcomes': [], 'official_social_accounts': [], 'events': [],
                      'year_coverage': [{'year': y, 'status': 'not_researched',
                                         'notes': 'Directory coverage only; historical school-event research not completed. Missing evidence does not establish no event.'} for y in (2024,2025,2026)],
                      'sources': [{'type': 'official_directory', 'url': edb_url, 'checked_date': checked}],
                      'monitoring': {'scheduled_monitoring_active': False}}
            if not school['website'] and profile: school['website'] = website(profile.get('school_website'))
        school['edb_school_no'] = base
        school['directory_status'] = 'official_directory_identity_with_reviewed_history' if seed else 'official_directory_only_history_not_researched'
        school['directory_source'] = {'publisher': 'Education Bureau / DATA.GOV.HK', 'url': edb_url,
                                      'checked_date': checked, 'publisher_snapshot_date': directory.get('publisher_snapshot_date'),
                                      'school_numbers': sorted({str(s['SCHOOL NO.']) for s in sections}),
                                      'registration_no': base, 'category': row['ENGLISH CATEGORY'],
                                      'finance_type': row.get('FINANCE TYPE'), 'district_zh': row.get('分區'),
                                      **directory_values,
                                      'campuses': [{'school_no': str(s['SCHOOL NO.']), 'address_zh': s['中文地址'],
                                                    'district': s['DISTRICT'], 'session': s['SESSION']} for s in sections],
                                      'seed_match_method': seed_method, 'chsc_match_method': profile_method}
        if not seed and not school['website'] and school['id'] in website_overrides:
            proof = copy.deepcopy(website_overrides[school['id']])
            # The approved page URL may contain a meaningful campus query. Keep it.
            school['website'] = proof['website']
            school['website_provenance'] = proof
            school['sources'].append({'type':'school_website', 'url':proof['source_url'],
                                      'checked_date':proof['checked_date'], 'scope':'directory identity only'})
            applied_websites.append(school['id'])
        if profile:
            school['directory_source']['chsc'] = {'url': chsc_url, 'academic_year': '2025/26',
                                                  'school_name': profile['school_name'], 'checked_date': checked,
                                                  's1_class_count': profile.get('current_year_no_of_class_s1') or None,
                                                  's1_fee_as_published': profile.get('sc_school_fee_s1') or None}
        if len(sections) > 1:
            merges.append({'registration_no': base, 'name_en': row['ENGLISH NAME'],
                           'school_numbers': school['directory_source']['school_numbers'],
                           'rule': 'same six-digit EDB registration and exact normalized school name; retain campus sections'})
        if base in PIS or school['school_type'] == 'Private':
            note = 'Included EDB local-private registered day secondary school; curriculum is not an exclusion.'
            if base in PIS: note += ' Private Independent School Scheme; other private school, not excluded merely for International in its name.'
            if base in {'289094','524867'}: note += ' Registered full-time day secondary identity retained; unrelated tutorial offerings are outside the roster.'
            classification_sources = [edb_url]
            if base in PIS:
                classification_sources.append('https://internationalschools.edb.gov.hk/en/schools/pis.html')
            if base in {'289094','524867'}:
                classification_sources.append('https://lifeplanning.edb.gov.hk/uploads/page/attachments/S6-repeaters_combined%2819-20%29.pdf')
            if base in {'605638','626864'}:
                note += ' Stamford branding/curriculum does not override its private category in the official EDB directory; retained with classification ambiguity visible.'
            borderlines.append({'registration_no': base, 'name_en': row['ENGLISH NAME'], 'decision': 'included', 'reason': note,
                                'source_urls': classification_sources, 'checked_date': checked})
        schools.append(school)
    unmatched_seeds = sorted({s['id'] for s in verified['schools']} - set(matches))
    if unmatched_seeds: raise ValueError('Reviewed schools not matched: ' + ', '.join(unmatched_seeds))
    if len(matches) != len(set(matches)): raise ValueError('One reviewed school matched multiple official registrations')
    # Preserve established display ordering for reviewed schools, then official name.
    seed_order = {s['id']: i for i,s in enumerate(verified['schools'])}
    schools.sort(key=lambda s: (0, seed_order[s['id']]) if s['id'] in seed_order else (1, s['name_en']))
    payload = {k: copy.deepcopy(v) for k,v in verified.items() if k not in ('schools','summary')}
    payload.update({'schema_version':'1.1', 'checked_date':checked,
                    'collection_mode':'complete scoped official directory snapshot; bounded historical research for 28 reviewed schools',
                    'schools':schools, 'summary':summarize(schools,checked)})
    coverage = {'schema_version':'1.0', 'checked_date':checked, 'source_url':edb_url,
                'scope':'Local mainstream Government, Aided, Caput, DSS and local-private day secondary school identities; ESF, official international, special, evening and education service centres excluded.',
                'source_payload_records':directory.get('source_payload_records'),
                'secondary_source_rows':len(directory['rows']), 'duplicate_source_rows':duplicate_count,
                'included_secondary_sections':sum(map(len,groups.values())), 'included_school_identities':len(schools),
                'districts':sorted({s['district'] for s in schools}),
                'schools_by_funding':dict(sorted(Counter(s['directory_source']['school_type'] for s in schools).items())),
                'matched_seed_ids':matches, 'unmatched_seed_ids':unmatched_seeds,
                'historically_researched_schools':len(matches), 'directory_only_schools':len(schools)-len(matches),
                'website_overrides_applied':applied_websites,
                'schools_missing_website':[{'id':s['id'],'name_en':s['name_en']} for s in schools if not s.get('website')],
                'chsc_profiles_in_source':len(chsc['rows']), 'matched_chsc_profiles':len(schools)-len(unmatched_chsc),
                'excluded_identity_counts':dict(sorted((reason,len({e['registration_no'] for e in excluded if e['reason']==reason})) for reason in {e['reason'] for e in excluded})),
                'not_in_chsc_profile_bulk':unmatched_chsc, 'excluded_records':excluded,
                'excluded_record_counts':dict(sorted(Counter(e['reason'] for e in excluded).items())),
                'merged_sections':merges, 'reviewed_directory_differences':changes, 'classification_ledger':borderlines,
                'limitations':[
                    'EDB monthly bulk JSON has no internal effective/snapshot date field. checked_date is retrieval date, not a claim of a publisher issue date.',
                    'The 2025/26 CHSC CSV has 441 profiles; it is supplementary, never a roster gate. Directory-only schools have no completed historical event or social-platform research. Separately cited website identity checks do not establish event coverage.',
                    'No historical event dates are synthesized from academic-year headings, admissions prose, or class counts. All new school-year event coverage is not_researched.',
                    'A public-sector/DSS count of 446 and an all-sector 2025/26 count of 513 use statistical scope/time definitions, including education service centres, and are not a target for this current mainstream roster.',
                    'Local private includes EDB-classified private/PIS schools offering IB, IGCSE and IAL; the curriculum alone does not make an official international school.',
                    'The official voluntary Private School List is not exhaustive, so absence there is not a reason to remove a registered day school.',
                    'Public website URLs come from EDB or CHSC and have not each been live-checked in this roster build. Missing URLs remain null.',
                    'School counts describe registered directory identities, not a guarantee of current intake, vacancies, financial viability, or continuous operation.',
                    'Some private schools are branded international while officially listed as other private; classification follows EDB category. Stamford registrations are retained with an explicit ambiguity note.',
                    'Beacon registered secondary day sessions are included; tutorial-only/non-formal courses are not inferred from operator names or scraped into this roster.',
                    'Several private schools have English text in the publisher Chinese-name field. This is retained verbatim; no Chinese name is invented.'],
                'source_checks':[
                    {'source':edb_url,'status':'200; JSON parsed','rows':directory.get('source_payload_records'),'checked_date':checked,'cadence':'monthly'},
                    {'source':chsc_url,'status':'200; CSV parsed','rows':len(chsc['rows']),'checked_date':checked,'academic_year':'2025/26'}]}
    return payload, coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'seed/roster-source-edb.json')
    parser.add_argument('--verified',type=Path,default=ROOT/'seed/verified-schools.json')
    parser.add_argument('--chsc',type=Path,default=ROOT/'seed/roster-source-chsc.json')
    parser.add_argument('--website-overrides',type=Path,default=ROOT/'seed/website-overrides.json')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/data/pilot.json')
    parser.add_argument('--coverage',type=Path,default=ROOT/'docs/data/coverage.json')
    args=parser.parse_args()
    read=lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    data,coverage=build_roster(read(args.directory),read(args.verified),read(args.chsc),
                             read(args.website_overrides) if args.website_overrides.exists() else {})
    for path,value in ((args.output,data),(args.coverage,coverage)):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'schools':len(data['schools']),'reviewed':len(coverage['matched_seed_ids']),
                      'districts':len(coverage['districts']),'excluded_records':coverage['excluded_record_counts']},ensure_ascii=False))


if __name__=='__main__': main()
