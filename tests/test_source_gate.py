"""Bài 4: kiểm tra nguồn, các trường hợp ngoài tests/test_validation.py. Offline."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent, SYSTEM_PROMPT
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

# Hai incident có thật trong snapshot GitHub và URL mà get_incident_details trả về.
H02, H02_URL = 'h02n9572mx9y', 'https://stspg.io/7pwv28hvkmz8'
XR3, XR3_URL = 'xr3myzj7ms51', 'https://stspg.io/pjgptg3cfc6n'


def details(call_id, incident_id):
    return tool_call(call_id, 'get_incident_details', json.dumps({'provider': 'github', 'incident_id': incident_id}))


class SourceGateTests(unittest.TestCase):
    def test_reminder_lists_observed_url_and_is_sent_to_model(self):
        fake = FakeProvider([details('1', H02), final('Đã xử lý.'), final('Đã xử lý. ' + H02_URL)])
        result = run_agent('x', fake, StatusTools(), max_steps=4)
        self.assertEqual(result['status'], 'completed')
        reminder = fake.histories[2][-1]
        self.assertEqual(reminder['role'], 'user')
        self.assertIn(H02_URL, reminder['content'])

    def test_incident_named_by_id_without_its_url_is_flagged(self):
        partial = f'{H02} ({H02_URL}) trỏ tới incident gộp {XR3}.'
        fake = FakeProvider([details('1', H02), details('2', XR3), final(partial), final(partial + ' ' + XR3_URL)])
        result = run_agent('x', fake, StatusTools(), max_steps=5)
        self.assertEqual(result['status'], 'completed')
        gate = [t for t in result['trace'] if t['event'] == 'validation_missing_source']
        self.assertEqual(gate[0]['missing'], [XR3_URL])

    def test_read_but_unmentioned_incident_is_not_required(self):
        fake = FakeProvider([details('1', H02), details('2', XR3), final(f'Chỉ {H02} liên quan: {H02_URL}')])
        result = run_agent('x', fake, StatusTools())
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(t['event'] == 'validation_missing_source' for t in result['trace']))

    def test_get_status_alone_does_not_require_incident_url(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"github"}'), final('Không có sự cố đang mở.')])
        self.assertEqual(run_agent('x', fake, StatusTools())['status'], 'completed')

    def test_prompt_asks_to_report_partial_results(self):
        for field in ('matching_incidents_in_last_50', 'updates_total', 'truncated'):
            self.assertIn(field, SYSTEM_PROMPT)

    def test_prompt_names_the_source_fields_to_cite(self):
        # Round 2: the prompt asks for the URL up front; the loop check stays as a safety net.
        self.assertIn('trường url', SYSTEM_PROMPT)
        self.assertIn('trường source', SYSTEM_PROMPT)


if __name__ == '__main__':
    unittest.main()
