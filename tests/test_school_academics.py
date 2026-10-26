import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/school-academics.py'
spec=importlib.util.spec_from_file_location('school_academics',SCRIPT) if SCRIPT.exists() else None
academic=importlib.util.module_from_spec(spec) if spec else None
if academic:spec.loader.exec_module(academic)

def row(name='甲校',en='Alpha School',**updates):
    value={'#':'1','學校名稱':name,'English Name':en,'Banding':'1A','Banding 原始估算':'1B–1A',
           'Banding 更新年份（DSE 年度）':'2026','Banding 準確度':'準確性高','Banding 推導方式':'大考按 2026 年數據推算',
           'Banding 來源（含 URL）':'大考（https://dse.bigexam.hk/zh-hk/ssp/school/1）',
           '大學最低入學要求達標率':'大約 88.1%','入學要求指標':'332A+2','升學數據性質':'學校自行公布',
           '升學數據年份':'2025','其他升學指標（學校公布）':'升讀本地學士學位 接近 65.1%；畢業生升學率 100%',
           '資料頁':'https://dse.bigexam.hk/zh-hk/ssp/school/1'}
    value.update(updates);return value

def school(id='a',zh='甲校',en='Alpha School'):
    return {'id':id,'name_zh':zh,'name_en':en,'reference_band':{'display':None},'events':[{'start_date':'2024-11-01'}],
            'university_outcomes':[{'cohort_year':2026,'rate_percent':90,'source_url':'https://school.test/results'}]}

class AcademicTests(unittest.TestCase):
    def compile(self,rows=None,schools=None,details=None):
        self.assertIsNotNone(academic,'Academic importer must exist')
        return academic.compile_seed(rows or [row()],details or [],schools or [school()],{'imported_date':'2026-10-26'})

    def test_exact_matching_is_one_to_one_and_rejects_ambiguity(self):
        seed=self.compile();self.assertEqual(seed['records'][0]['id'],'a')
        with self.assertRaisesRegex(ValueError,'multiple|Duplicate'):
            self.compile([row(),row()])
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            self.compile([row()], [school(),school('b','乙校','Alpha School')])
        with self.assertRaisesRegex(ValueError,'unmatched'):
            self.compile([row('未知校','Unknown')])

    def test_rates_preserve_qualifiers_years_and_threshold_meaning(self):
        r=self.compile()['records'][0]['academic_reference']
        self.assertEqual(r['entry_requirements']['rate_percent'],88.1)
        self.assertEqual(r['entry_requirements']['reported_value'],'大約 88.1%')
        self.assertEqual(r['entry_requirements']['cohort_year'],2025)
        self.assertEqual(r['entry_requirements']['kind'],'entry_requirement')
        self.assertEqual(r['progression'][0]['reported_value'],'接近 65.1%')
        self.assertEqual(r['verification_status'],'secondary_compilation_unverified')
        self.assertIsNone(self.compile([row(**{'大學最低入學要求達標率':''})])['records'][0]['academic_reference']['entry_requirements'])
        self.assertEqual(self.compile([row(**{'大學最低入學要求達標率':'0%'})])['records'][0]['academic_reference']['entry_requirements']['rate_percent'],0)
        with self.assertRaisesRegex(ValueError,'percentage'):self.compile([row(**{'大學最低入學要求達標率':'101%'})])

    def test_mixed_degree_subdegree_claim_is_not_a_university_entry_rate(self):
        r=self.compile([row(**{'入學要求指標':'學士或副學位最低要求'})])['records'][0]['academic_reference']
        self.assertIsNone(r['entry_requirements'])
        self.assertEqual(r['unclassified_measure']['kind'],'unclassified_degree_subdegree_measure')

    def test_school_subjects_never_take_national_benchmarks(self):
        detail={'學校名稱':'甲校','DSE 年份':'2025','中文 L5+':'大約 30%','中文 L4+':'','全港 L5+':'14%','資料頁':row()['資料頁']}
        r=self.compile(details=[detail])['records'][0]['academic_reference']['subject_results']
        self.assertEqual([(x['metric'],x['rate_percent']) for x in r['school_metrics']],[('中文 L5+',30)])
        self.assertEqual(r['hk_day_school_benchmarks'][0]['rate_percent'],14)
        with self.assertRaisesRegex(ValueError,'detail'):self.compile(details=[{**detail,'學校名稱':'未知校'}])

    def test_overlay_preserves_events_results_and_owner_corrections(self):
        s=school();s['reference_band']={'display':'1B','year':2026,'source_type':'user_correction'}
        before=copy.deepcopy(s);seed=self.compile(schools=[s])
        result=academic.apply_enrichment([s],seed)[0]
        self.assertEqual(result['reference_band'],before['reference_band'])
        self.assertEqual(result['events'],before['events'])
        self.assertEqual(result['university_outcomes'],before['university_outcomes'])
        self.assertTrue(result['academic_reference']['band_conflict'])
        self.assertEqual(s,before,'Overlay must not mutate source records')
        self.assertEqual(academic.apply_enrichment([result],seed),[result],'Repeated overlay must be idempotent')

    def test_current_bands_use_highest_range_but_stale_remains_history(self):
        seed=self.compile();self.assertEqual(academic.apply_enrichment([school()],seed)[0]['reference_band']['display'],'1A')
        old=self.compile([row(**{'Banding 更新年份（DSE 年度）':'2015'})])
        result=academic.apply_enrichment([school()],old)[0]
        self.assertIsNone(result['reference_band'].get('display'))
        self.assertEqual(result['academic_reference']['band']['year'],2015)
        with self.assertRaisesRegex(ValueError,'highest'):self.compile([row(**{'Banding':'1B'})])

    def test_official_thresholds_require_school_identity_and_keep_cohorts(self):
        s=school();s['website']='https://school.test/'
        proof={'id':'a','name_zh':'甲校','source_url':'https://school.test/results','verification_status':'school_page_verified','checked_date':'2026-10-26',
               'entry_requirements':[{'metric':'332A33','cohort_year':2026,'reported_value':'63.6%'}]}
        result=academic.apply_enrichment([s],self.compile(),{'schools':[proof]})[0]
        self.assertEqual(result['exam_entry_requirements'][0]['rate_percent'],63.6)
        self.assertEqual(result['academic_reference']['entry_requirements']['cohort_year'],2025)
        with self.assertRaisesRegex(ValueError,'official'):
            academic.apply_enrichment([s],self.compile(),{'schools':[{**proof,'source_url':'https://aggregator.test/'}]})

    def test_rebuild_real_inputs_preserves_original_evidence_and_owner_bands(self):
        root=SCRIPT.parents[1]
        read=lambda p:json.loads(p.read_text(encoding='utf-8'))
        seed=read(root/'seed/academic-reference-2026.json')
        source=read(root/'seed/verified-schools.json')
        artifacts=root/'tests/artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as folder:
            output=Path(folder)/'pilot.json';coverage=Path(folder)/'coverage.json'
            run=subprocess.run([sys.executable,'-X','utf8',str(root/'scripts/school-roster.py'),'--output',str(output),'--coverage',str(coverage)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stderr)
            data=read(output)
        self.assertEqual(len(seed['records']),439)
        self.assertEqual(len(data['schools']),478)
        byid={s['id']:s for s in data['schools']}
        for original in source['schools']:
            for key,value in original.items():
                if key!='reference_band':self.assertEqual(byid[original['id']][key],value,(original['id'],key))
        for sid in ('diocesan-boys-school','st-margarets-coeducational-english-secondary-primary'):
            self.assertEqual(byid[sid]['reference_band']['display'],'1B')
            self.assertEqual(byid[sid]['reference_band']['source_type'],'user_correction')
        summary=data['academic_enrichment']
        self.assertEqual(summary['current_reference_bands'],425)
        self.assertEqual(summary['imported_entry_requirement_claims'],171)
        self.assertEqual(summary['unclassified_degree_subdegree_claims'],99)
        self.assertEqual(summary['schools_with_imported_progression_claims'],279)
        self.assertEqual(summary['schools_with_imported_subject_statistics'],263)
        for s in data['schools']:
            b=s['reference_band']
            if b.get('display'):self.assertGreaterEqual(b['year'],2024)
        self.assertEqual(byid['edb-510700']['exam_entry_requirements'][1]['rate_percent'],63.6)

if __name__=='__main__':unittest.main()
