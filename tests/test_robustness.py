"""Bài 2: các nhánh lỗi mà test_lab.py chưa phủ. Offline, dùng fake provider."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final


class FailingProvider:
    """Ném lỗi `failures` lần đầu rồi trả các response còn lại."""
    def __init__(self, failures, responses=()):
        self.failures, self.responses = failures, iter(responses)
        self.histories = []
    def complete(self, messages, schemas):
        self.histories.append(list(messages))
        if self.failures:
            self.failures -= 1
            raise RuntimeError('Provider trả HTTP 503; kiểm tra model, key và quota.')
        return next(self.responses)


class BrokenTools(StatusTools):
    def execute(self, name, args):
        raise KeyError('incident_updates')


@patch('agent.time.sleep')
class RobustnessTests(unittest.TestCase):
    def test_provider_error_ends_run_with_error(self, _sleep):
        result = run_agent('x', FailingProvider(failures=99), StatusTools())
        self.assertEqual(result['status'], 'error')
        self.assertIn('503', result['error'])
        self.assertEqual(result['trace'][-1]['event'], 'provider_error')

    def test_transient_provider_error_is_retried(self, _sleep):
        result = run_agent('x', FailingProvider(failures=1, responses=[final('ok')]), StatusTools())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([t['event'] for t in result['trace']], ['provider_retry', 'model'])

    def test_unexpected_tool_exception_becomes_observation(self, _sleep):
        fake = FakeProvider([tool_call('c1', 'get_status', '{"provider":"github"}'), final('Không đủ dữ liệu')])
        result = run_agent('x', fake, BrokenTools())
        self.assertEqual(result['status'], 'completed')
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertEqual((sent['ok'], sent['error']), (False, 'TOOL_ERROR'))

    def test_non_object_arguments_are_invalid(self, _sleep):
        fake = FakeProvider([tool_call('c1', 'get_status', '["github"]'), final()])
        run_agent('x', fake, StatusTools())
        self.assertEqual(json.loads(fake.histories[1][-1]['content'])['error'], 'INVALID_ARGUMENTS')

    def test_empty_arguments_mean_no_arguments(self, _sleep):
        fake = FakeProvider([tool_call('c1', 'missing_tool', ''), final()])
        run_agent('x', fake, StatusTools())
        self.assertEqual(json.loads(fake.histories[1][-1]['content'])['error'], 'UNKNOWN_TOOL')

    def test_other_finish_reason_is_not_completed(self, _sleep):
        filtered = final('')
        filtered['finish'] = 'content_filter'
        self.assertEqual(run_agent('x', FakeProvider([filtered]), StatusTools())['status'], 'error')

    def test_tool_timeout_is_traced_and_run_continues(self, _sleep):
        fake = FakeProvider([tool_call('c1', 'get_status', '{"provider":"cloudflare"}'), final('Không kiểm tra được Cloudflare')])
        result = run_agent('x', fake, StatusTools(fail=True))
        self.assertEqual(result['status'], 'completed')
        tool = next(t for t in result['trace'] if t['event'] == 'tool')
        self.assertEqual(tool['result']['error'], 'TimeoutError')

    def test_every_trace_entry_has_event(self, _sleep):
        fake = FakeProvider([tool_call('c1', 'get_status', '{'), tool_call('c2', 'get_status', '{"provider":"github"}')])
        result = run_agent('x', fake, StatusTools(), max_steps=2)
        self.assertEqual(result['status'], 'max_steps')
        self.assertTrue(all('event' in t for t in result['trace']))


if __name__ == '__main__':
    unittest.main()
