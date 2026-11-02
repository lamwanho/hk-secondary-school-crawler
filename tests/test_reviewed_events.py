"""Reviewed corrections survive directory rebuilds without replacing school facts."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('roster_review', ROOT / 'scripts/school-roster.py')
roster = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roster)


class ReviewedEventTests(unittest.TestCase):
    def test_reviewed_overlay_preserves_identity_academics_and_history(self):
        data = {'schools': [{'id': 'sample', 'events': [{'event_id': 'old'}], 'academic_reference': {'keep': True}, 'year_coverage': [{'year': 2024, 'status': 'not_researched'}, {'year': 2026, 'status': 'not_researched'}]}]}
        original = copy.deepcopy(data)
        event = {'event_id': 'new', 'event_year': 2026, 'verification': {'checked_date': '2026-11-02'}}
        overlay = {'schools': [{'id': 'sample', 'events': [event]}]}
        roster.apply_reviewed_events(data, overlay)
        roster.apply_reviewed_events(data, overlay)
        school = data['schools'][0]
        self.assertEqual(school['events'], [original['schools'][0]['events'][0], event])
        self.assertEqual(school['academic_reference'], {'keep': True})
        self.assertEqual(school['year_coverage'][0], original['schools'][0]['year_coverage'][0])
        self.assertEqual(school['year_coverage'][1]['status'], 'dated_event_found')
        with self.assertRaises(ValueError):
            roster.apply_reviewed_events(data, {'schools': [{'id': 'missing', 'events': [event]}]})

    def test_npl_official_correction_separates_visit_and_full_talks(self):
        seed = json.loads((ROOT / 'seed/reviewed-events.json').read_text(encoding='utf-8'))
        event = next(s for s in seed['schools'] if s['id'] == 'edb-552801')['events'][0]
        self.assertEqual(event['start_date'], '2026-11-21')
        self.assertEqual((event['start_time'], event['end_time']), ('09:00', '16:00'))
        self.assertFalse(event['visit_registration']['required'])
        self.assertTrue(event['talk_registration']['required'])
        self.assertEqual(event['talk_registration']['status'], 'full')
        self.assertEqual((event['talk_registration']['opens_date'], event['talk_registration']['opens_time']), ('2026-11-01', '09:00'))
        self.assertEqual(event['talk_registration']['checked_date'], '2026-11-02')
        self.assertEqual([s['start_time'] for s in event['sessions']], ['10:00', '14:30'])
        self.assertTrue(all(s['registration_status'] == 'full' for s in event['sessions']))
        self.assertEqual(event['verification']['level'], 'school_page_verified')

    def test_hkuga_uses_correct_page_and_separates_lottery_from_general_visits(self):
        seed = json.loads((ROOT / 'seed/verified-schools.json').read_text(encoding='utf-8'))
        school = next(s for s in seed['schools'] if s['id'] == 'hkuga-college')
        event = next(e for e in school['events'] if e['event_year'] == 2026)
        page = 'https://www.hkugac.edu.hk/engage/as-a-student/admission-info-day'
        self.assertEqual(event['source_urls'], [page])
        self.assertEqual(event['talk_registration']['booking_url'], page)
        self.assertEqual(event['start_date'], '2026-12-05')
        self.assertEqual((event['start_time'], event['end_time']), ('08:30', '12:30'))
        self.assertIsNone(event['visit_registration']['required'])
        self.assertEqual(event['talk_registration']['opens_date'], '2026-11-02')
        self.assertIsNone(event['talk_registration']['opens_time'])
        self.assertEqual(event['talk_registration']['closes_time'], '16:00')
        self.assertNotEqual(event['talk_registration']['status'], 'not_yet_open')
        self.assertIn('randomisation', event['talk_registration']['method'])
        self.assertEqual(len(event['sessions']), 3)
