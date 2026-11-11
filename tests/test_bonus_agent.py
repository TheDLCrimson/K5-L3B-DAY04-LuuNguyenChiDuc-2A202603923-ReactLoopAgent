"""Bonus: agent dùng prompt và schemas của bộ tools, giới hạn retry khi bị rate limit. Offline."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent, SYSTEM_PROMPT, TOOLSET_RULES, _retry_after_seconds
from bonus.tools import BonusTools, SCHEMAS as BONUS_SCHEMAS
from status_tools import StatusTools, SCHEMAS
from test_lab import FakeProvider, tool_call, final


class RecordingProvider(FakeProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.schemas = []
    def complete(self, messages, schemas):
        self.schemas.append(schemas)
        return super().complete(messages, schemas)


class LimitedTools:
    """Tool giả: trả RATE_LIMITED với retry_after cho trước ở lần gọi đầu, sau đó trả kết quả."""
    def __init__(self, retry_after):
        self.retry_after, self.calls = retry_after, 0
    def execute(self, name, args):
        self.calls += 1
        if self.calls == 1:
            return {'ok': False, 'error': 'RATE_LIMITED', 'http_status': 429, 'retry_after': self.retry_after}
        return {'provider': 'npm', 'overall': {'indicator': 'none'}}


def vercel(call_id):
    return tool_call(call_id, 'get_vercel_status', '{}')


class ToolsetTests(unittest.TestCase):
    def test_bonus_tools_bring_their_prompt_and_schemas(self):
        fake = RecordingProvider([final()])
        run_agent('x', fake, BonusTools())
        system = fake.histories[0][0]['content']
        self.assertTrue(system.startswith(BonusTools.system_prompt))
        self.assertIn(TOOLSET_RULES, system)
        self.assertIs(fake.schemas[0], BONUS_SCHEMAS)

    def test_main_tools_keep_the_main_prompt_and_schemas(self):
        fake = RecordingProvider([final()])
        run_agent('x', fake, StatusTools())
        self.assertEqual(fake.histories[0][0]['content'], SYSTEM_PROMPT)
        self.assertIs(fake.schemas[0], SCHEMAS)


@patch('agent.time.sleep')
class RateLimitTests(unittest.TestCase):
    def test_fourth_call_after_three_429s_is_blocked_not_executed(self, sleep):
        tools = BonusTools(scenario='rate_limit_always')
        fake = FakeProvider([vercel('1'), vercel('2'), vercel('3'), vercel('4'), final('Vercel: chưa kiểm tra được')])
        result = run_agent('x', fake, tools, max_steps=6)
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)
        executed = [t for t in result['trace'] if t['event'] == 'tool']
        self.assertEqual(len(executed), 3)
        blocked = [t for t in result['trace'] if t['event'] == 'rate_limit_blocked']
        self.assertEqual(blocked[0]['result']['error'], 'RETRY_LIMIT_REACHED')
        self.assertEqual(json.loads(fake.histories[4][-1]['content'])['error'], 'RETRY_LIMIT_REACHED')

    def test_429_once_then_success_is_not_blocked(self, sleep):
        tools = BonusTools(scenario='rate_limit_once')
        fake = FakeProvider([vercel('1'), vercel('2'), final()])
        result = run_agent('x', fake, tools, max_steps=5)
        self.assertEqual(json.loads(fake.histories[2][-1]['content'])['provider'], 'vercel')
        self.assertNotIn('rate_limit_blocked', [t['event'] for t in result['trace']])
        sleep.assert_not_called()  # retry_after_seconds giả lập là 0

    @patch('agent.time.monotonic', return_value=100.0)
    def test_retry_waits_out_retry_after(self, _monotonic, sleep):
        tools = LimitedTools(retry_after='5')
        npm = tool_call('1', 'get_npm_status', '{}')
        fake = FakeProvider([npm, tool_call('2', 'get_npm_status', '{}'), final()])
        result = run_agent('x', fake, tools, max_steps=5)
        sleep.assert_called_once_with(5.0)
        self.assertIn('rate_limit_wait', [t['event'] for t in result['trace']])
        self.assertEqual(tools.calls, 2)

    @patch('agent.time.monotonic', return_value=100.0)
    def test_retry_after_beyond_budget_is_not_retried(self, _monotonic, sleep):
        tools = LimitedTools(retry_after='120')
        fake = FakeProvider([tool_call('1', 'get_npm_status', '{}'), tool_call('2', 'get_npm_status', '{}'), final()])
        result = run_agent('x', fake, tools, max_steps=5)
        sleep.assert_not_called()
        self.assertEqual(tools.calls, 1)
        blocked = next(t for t in result['trace'] if t['event'] == 'rate_limit_blocked')
        self.assertEqual(blocked['result']['error'], 'RETRY_AFTER_TOO_LONG')


class RetryAfterParsingTests(unittest.TestCase):
    def test_seconds_http_date_and_missing(self):
        self.assertEqual(_retry_after_seconds({'retry_after_seconds': 0}), 0.0)
        self.assertEqual(_retry_after_seconds({'retry_after': '2'}), 2.0)
        self.assertEqual(_retry_after_seconds({'retry_after': 'Wed, 21 Oct 2015 07:28:00 GMT'}), 0.0)  # đã qua
        self.assertEqual(_retry_after_seconds({'retry_after': None}), 0.0)
        self.assertEqual(_retry_after_seconds({'retry_after': 'not a date'}), 0.0)


if __name__ == '__main__':
    unittest.main()
