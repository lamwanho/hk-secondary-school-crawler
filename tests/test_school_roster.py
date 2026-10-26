import copy
import importlib.util
import inspect
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'school-roster.py'
build = None
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('school_roster', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = module.build_roster


def record(number='510777000133', name="DIOCESAN BOYS' SCHOOL", **values):
    row = {'SCHOOL NO.': number, 'ENGLISH NAME': name, '中文名稱': '拔萃男書院',
           'ENGLISH CATEGORY': 'Direct Subsidy Scheme Secondary Schools', 'SCHOOL LEVEL': 'SECONDARY',
           'SESSION': 'WHOLE DAY', 'DISTRICT': 'KOWLOON CITY', '分區': '九龍城區',
           'FINANCE TYPE': 'DIRECT SUBSIDY SCHEME', 'STUDENTS GENDER': 'BOYS',
           '中文地址': '九龍亞皆老街131號', 'WEBSITE': 'http://www.dbs.edu.hk'}
    row.update(values)
    return row


class RosterTests(unittest.TestCase):
    def run_build(self, rows, seeds=None, chsc=None):
        self.assertTrue(callable(build), 'Roster builder must exist')
        return build({'rows': rows, 'source_url': 'https://www.edb.gov.hk/data.json', 'checked_date': '2026-10-26'},
                     {'schools': seeds or [], 'summary': {}}, {'rows': chsc or [], 'source_url': 'https://www.chsc.hk/data.csv'})

    def test_campus_sections_merge_but_distinct_registrations_do_not(self):
        rows = [record(), record('510777000233'), record('511714000133', "DIOCESAN GIRLS' SCHOOL", **{'中文名稱': '拔萃女書院'})]
        data, coverage = self.run_build(rows)
        self.assertEqual(len(data['schools']), 2)
        self.assertEqual(len(data['schools'][0]['directory_source']['school_numbers']), 2)
        self.assertEqual(len(coverage['merged_sections']), 1)

    def test_seed_identity_facts_and_events_survive(self):
        seed = {'id': 'dbs', 'name_en': "Diocesan Boys' School", 'name_zh': '拔萃男書院',
                'website': 'https://www.dbs.edu.hk/', 'school_address_zh': 'Old cited address',
                'reference_band': {'display': '1B', 'status': 'user correction'},
                'school_fee': {'amount_hkd': 65000}, 's1_intake': {'total': 240, 'external': 92},
                'events': [{'event_id': 'reviewed', 'start_date': '2026-11-01'}], 'university_outcomes': [{'rate': 91}]}
        original = copy.deepcopy(seed)
        data, coverage = self.run_build([record()], [seed])
        for key, value in original.items(): self.assertEqual(data['schools'][0][key], value)
        self.assertEqual(coverage['matched_seed_ids'], ['dbs'])
        self.assertEqual(seed, original)

    def test_excludes_international_special_evening_and_service_centres(self):
        rows = [record(), record('200000000133', 'INTERNATIONAL', **{'ENGLISH CATEGORY': 'International Schools (Secondary)'}),
                record('200001000133', 'SPECIAL', **{'ENGLISH CATEGORY': 'Aided Special Schools'}),
                record('200002000134', 'EVENING', SESSION='EVENING'), record('511072000133', 'ARTS & TECHNOLOGY EDUCATION CENTRE')]
        data, coverage = self.run_build(rows)
        self.assertEqual(len(data['schools']), 1)
        self.assertEqual(len(coverage['excluded_records']), 4)

    def test_other_private_international_named_school_is_not_false_excluded(self):
        row = record('553867000333', 'INTERNATIONAL CHRISTIAN QUALITY MUSIC SECONDARY AND PRIMARY SCHOOL', **{'ENGLISH CATEGORY': 'Private Secondary Schools (Day/Evening)', 'FINANCE TYPE': 'PRIVATE INDEPENDENT SCH SCHEME'})
        data, _ = self.run_build([row])
        self.assertEqual(len(data['schools']), 1)
        self.assertEqual(data['schools'][0]['school_type'], 'Private')

    def test_unknown_events_and_band_stay_unknown_and_dash_fee_not_zero(self):
        ch = {'school_name': "Diocesan Boys' School", 'school_website': 'https://www.dbs.edu.hk', 'sc_school_fee_s1': '-'}
        data, _ = self.run_build([record()], chsc=[ch]); school=data['schools'][0]
        self.assertEqual(school['events'], [])
        self.assertIsNone(school['reference_band']['display'])
        self.assertIsNone(school['school_fee']['amount_hkd'])
        self.assertEqual({x['status'] for x in school['year_coverage']}, {'not_researched'})

    def test_exact_duplicate_rows_do_not_inflate_identity(self):
        data, coverage = self.run_build([record(), record()])
        self.assertEqual(len(data['schools']), 1)
        self.assertEqual(coverage['duplicate_source_rows'], 1)

    def test_unconfirmed_social_candidates_are_not_counted_as_official_evidence(self):
        seed = {'id': 'dbs', 'name_en': "Diocesan Boys' School", 'name_zh': '拔萃男書院',
                'official_social_accounts': [{'url': 'https://facebook.com/candidate', 'official_evidence_url': None}]}
        data, _ = self.run_build([record()], [seed])
        self.assertEqual(data['summary']['schools_with_official_social_evidence'], 0)

    def test_esf_private_registration_excluded_but_stamford_follows_publisher_private_category(self):
        rows = [record('569747000233', 'DISCOVERY COLLEGE', **{'ENGLISH CATEGORY': 'Private Secondary Schools (Day/Evening)'}),
                record('605638000133', 'STAMFORD AMERICAN SCHOOL HONG KONG', **{'ENGLISH CATEGORY': 'Private Secondary Schools (Day/Evening)'})]
        data, coverage = self.run_build(rows)
        self.assertEqual(len(data['schools']), 1)
        self.assertEqual(data['schools'][0]['edb_school_no'], '605638')
        self.assertEqual(coverage['excluded_records'][0]['reason'], 'esf_school')

    def test_distinct_names_on_same_registration_require_review(self):
        self.assertTrue(callable(build))
        with self.assertRaisesRegex(ValueError, 'Different names'):
            self.run_build([record(), record('510777000233', 'UNRELATED SCHOOL')])

    def test_chsc_numeric_fee_is_not_converted_from_class_count(self):
        profile={'school_name': "Diocesan Boys' School", 'school_website': 'https://dbs.edu.hk',
                 'sc_school_fee_s1': '"$63,330"', 'current_year_no_of_class_s1': '6'}
        data,_=self.run_build([record()],chsc=[profile]); school=data['schools'][0]
        self.assertEqual(school['school_fee']['amount_hkd'],63330)
        self.assertIsNone(school['s1_intake']['total'])

    def test_verified_missing_website_override_keeps_original_edb_null(self):
        self.assertTrue(callable(build))
        self.assertIn('website_overrides',inspect.signature(build).parameters,'Builder must support audited website overrides')
        row=record(WEBSITE='N.A.')
        proof={'website':'https://www.dbs.edu.hk/campus.php?wid=235',
               'source_url':'https://www.dbs.edu.hk/contact/', 'checked_date':'2026-10-26',
               'verification_level':'official_school_page_identity_verified', 'notes':'School name and registration match.'}
        data,coverage=build({'rows':[row]}, {'schools':[]}, {'rows':[]}, {'edb-510777':proof})
        school=data['schools'][0]
        self.assertEqual(school['website'],proof['website'])
        self.assertIsNone(school['directory_source']['website'])
        self.assertEqual(school['website_provenance'],proof)
        self.assertEqual(coverage['website_overrides_applied'],['edb-510777'])

    def test_unverified_website_override_is_rejected(self):
        self.assertTrue(callable(build))
        self.assertIn('website_overrides',inspect.signature(build).parameters,'Builder must support audited website overrides')
        with self.assertRaisesRegex(ValueError,'official'):
            build({'rows':[record(WEBSITE='N.A.')]},{'schools':[]},{'rows':[]},
                  {'edb-510777':{'website':'https://dbs.edu.hk/','source_url':'https://search.example/result'}})

    def test_real_official_snapshot_reconciles_and_preserves_all_reviewed_fields(self):
        self.assertTrue(callable(build))
        root=SCRIPT.parents[1]
        read=lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
        source=read(root/'seed/roster-source-edb.json')
        verified=read(root/'seed/verified-schools.json')
        data,coverage=build(source,verified,read(root/'seed/roster-source-chsc.json'))
        self.assertEqual((len(data['schools']),len(coverage['districts'])),(478,18))
        self.assertEqual(coverage['schools_by_funding'],{'Aided':355,'Caput':2,'DSS':57,'Government':29,'Private':35})
        self.assertEqual(coverage['matched_chsc_profiles'],441)
        self.assertEqual(len(coverage['matched_seed_ids']),28)
        self.assertEqual(coverage['secondary_source_rows'], coverage['duplicate_source_rows']+len(coverage['excluded_records'])+coverage['included_secondary_sections'])
        self.assertEqual(coverage['included_secondary_sections'],494)
        self.assertEqual(coverage['duplicate_source_rows'],15)
        self.assertEqual(sum(len(m['school_numbers'])-1 for m in coverage['merged_sections']),16)
        byid={s['id']:s for s in data['schools']}
        for seed in verified['schools']:
            for key,value in seed.items(): self.assertEqual(byid[seed['id']][key],value,(seed['id'],key))
        self.assertEqual(data['summary']['events'],60)
        self.assertEqual(data['summary']['dated_events'],57)
        self.assertEqual(data['summary']['schools_with_official_social_evidence'],5)
        self.assertEqual(sum(not s['website'] for s in data['schools']),6)
        bases={s['edb_school_no'] for s in data['schools']}
        self.assertTrue({'289094','524867','543560','553190','560138','171026','231622'}.issubset(bases))
        self.assertFalse({'567485','569747','511072','517160','519162'}.intersection(bases))
        self.assertEqual(len(bases),len(data['schools']))
        corrected,audit=build(source,verified,read(root/'seed/roster-source-chsc.json'),read(root/'seed/website-overrides.json'))
        self.assertEqual(len(audit['website_overrides_applied']),6)
        self.assertEqual(audit['schools_missing_website'],[])
        self.assertEqual(sum(s['directory_source']['website'] is None for s in corrected['schools']),6)
        for school in corrected['schools']:
            if 'website_provenance' in school:
                self.assertIsNone(school['directory_source']['website'])
                self.assertEqual(school['website_provenance']['verification_level'],'official_school_page_identity_verified')


if __name__ == '__main__': unittest.main()
