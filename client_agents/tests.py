import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in [REPO_ROOT, BACKEND_ROOT]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase
from pipeline.core.data.expression import ConstantTemplate

from tasknexus_client_agent.components.collections.agent import ClientAgentService
from tasknexus_gem.entries.client.build import build_android

from .consumers import AgentConsumer

from .log_reader import SEARCH_CHUNK_BYTES, read_window, search_in_log


class LogReaderTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.log_path = Path(self.tmpdir.name) / 'task_1.log'

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_bytes(self, data: bytes):
        self.log_path.write_bytes(data)

    def test_read_window_from_tail_and_backward_pagination(self):
        self._write_bytes(b'0123456789')

        tail = read_window(self.log_path, cursor=None, direction='backward', limit_bytes=4)
        self.assertEqual(tail['window_start'], 6)
        self.assertEqual(tail['window_end'], 10)
        self.assertEqual(tail['text'], '6789')
        self.assertTrue(tail['has_more_backward'])
        self.assertFalse(tail['has_more_forward'])

        prev = read_window(self.log_path, cursor=tail['next_backward_cursor'], direction='backward', limit_bytes=4)
        self.assertEqual(prev['window_start'], 2)
        self.assertEqual(prev['window_end'], 6)
        self.assertEqual(prev['text'], '2345')

        first = read_window(self.log_path, cursor=prev['next_backward_cursor'], direction='backward', limit_bytes=10)
        self.assertEqual(first['window_start'], 0)
        self.assertEqual(first['window_end'], 2)
        self.assertEqual(first['text'], '01')
        self.assertFalse(first['has_more_backward'])

    def test_read_window_forward(self):
        self._write_bytes(b'abcdefghij')

        chunk = read_window(self.log_path, cursor=3, direction='forward', limit_bytes=4)
        self.assertEqual(chunk['window_start'], 3)
        self.assertEqual(chunk['window_end'], 7)
        self.assertEqual(chunk['text'], 'defg')
        self.assertTrue(chunk['has_more_backward'])
        self.assertTrue(chunk['has_more_forward'])

    def test_read_window_empty_file(self):
        data = read_window(self.log_path, cursor=None, direction='backward', limit_bytes=1024)
        self.assertEqual(data['file_size'], 0)
        self.assertEqual(data['text'], '')
        self.assertFalse(data['has_more_backward'])
        self.assertFalse(data['has_more_forward'])

    def test_read_window_invalid_utf8_is_replaced(self):
        self._write_bytes(b'abc\xff\xfedef')
        data = read_window(self.log_path, cursor=None, direction='backward', limit_bytes=20)
        self.assertIn('abc', data['text'])
        self.assertIn('def', data['text'])
        self.assertIn('\ufffd', data['text'])

    def test_search_in_log_with_pagination(self):
        self._write_bytes(b'error line 1\nnormal\nerror line 2\nerror line 3\n')

        first_page = search_in_log(self.log_path, query='error', limit=2)
        self.assertEqual(len(first_page['hits']), 2)
        self.assertTrue(first_page['has_more'])
        self.assertIsNotNone(first_page['next_cursor'])

        second_page = search_in_log(
            self.log_path,
            query='error',
            cursor=first_page['next_cursor'],
            limit=2,
        )
        self.assertEqual(len(second_page['hits']), 1)
        self.assertFalse(second_page['has_more'])

    def test_search_in_log_no_hits(self):
        self._write_bytes(b'alpha\nbeta\ngamma\n')
        data = search_in_log(self.log_path, query='delta', limit=10)
        self.assertEqual(data['hits'], [])
        self.assertFalse(data['has_more'])
        self.assertIsNone(data['next_cursor'])

    def test_search_cross_chunk_boundary(self):
        prefix = b'a' * (SEARCH_CHUNK_BYTES - 2)
        payload = prefix + b'ABCD' + b'z' * 32
        self._write_bytes(payload)

        data = search_in_log(self.log_path, query='ABCD', limit=5)
        self.assertEqual(len(data['hits']), 1)
        self.assertEqual(data['hits'][0]['offset'], SEARCH_CHUNK_BYTES - 2)


class AgentConsumerTests(SimpleTestCase):
    def test_normalize_task_result_accepts_dict_only(self):
        self.assertEqual(AgentConsumer._normalize_task_result({'file_name': 'demo.apk'}), {'file_name': 'demo.apk'})
        self.assertEqual(AgentConsumer._normalize_task_result('{"file_name":"demo.apk"}'), {})
        self.assertEqual(AgentConsumer._normalize_task_result(None), {})

    def test_handle_task_completed_preserves_structured_result(self):
        consumer = AgentConsumer()
        consumer.agent = SimpleNamespace(name='demo-agent')
        consumer.update_agent_task_status = AsyncMock()
        consumer._append_log_file = AsyncMock()
        consumer.channel_layer = SimpleNamespace(group_send=AsyncMock())

        async_to_sync(consumer.handle_task_completed)(
            {
                'task_id': 12,
                'exit_code': 0,
                'stderr': '',
                'result': {'file_name': 'demo.apk'},
            }
        )

        update_args = consumer.update_agent_task_status.await_args.args
        update_kwargs = consumer.update_agent_task_status.await_args.kwargs
        self.assertEqual(update_args[0], 12)
        self.assertEqual(update_kwargs['status'], 'COMPLETED')
        self.assertEqual(update_kwargs['result'], {'file_name': 'demo.apk'})

    def test_handle_task_completed_defaults_to_empty_result(self):
        consumer = AgentConsumer()
        consumer.agent = SimpleNamespace(name='demo-agent')
        consumer.update_agent_task_status = AsyncMock()
        consumer._append_log_file = AsyncMock()
        consumer.channel_layer = SimpleNamespace(group_send=AsyncMock())

        async_to_sync(consumer.handle_task_completed)(
            {
                'task_id': 13,
                'exit_code': 1,
                'stderr': 'boom',
            }
        )

        update_kwargs = consumer.update_agent_task_status.await_args.kwargs
        self.assertEqual(update_kwargs['status'], 'FAILED')
        self.assertEqual(update_kwargs['result'], {})


class ClientAgentServiceTests(SimpleTestCase):
    class DummyData:
        def __init__(self, outputs=None):
            self._outputs = outputs or {}
            self.outputs = SimpleNamespace(ex_data=None)

        def get_one_of_outputs(self, key, default=None):
            return self._outputs.get(key, default)

        def set_outputs(self, key, value):
            self._outputs[key] = value

    def test_schedule_exposes_result_output(self):
        service = ClientAgentService()
        service.finish_schedule = Mock()
        data = self.DummyData(outputs={'task_id': '42'})
        task = SimpleNamespace(
            status='COMPLETED',
            exit_code=0,
            stdout='ok',
            stderr='',
            result={'file_name': 'demo.apk'},
            error_message='',
        )

        with patch('client_agents.models.AgentTask.objects.get', return_value=task):
            completed = service.schedule(data, parent_data=None)

        self.assertTrue(completed)
        self.assertEqual(data._outputs['result'], {'file_name': 'demo.apk'})
        self.assertEqual(data._outputs['exit_code'], 0)
        service.finish_schedule.assert_called_once()

    def test_schedule_defaults_result_to_empty_dict(self):
        service = ClientAgentService()
        service.finish_schedule = Mock()
        data = self.DummyData(outputs={'task_id': '42'})
        task = SimpleNamespace(
            status='FAILED',
            exit_code=1,
            stdout='',
            stderr='boom',
            result='not-a-dict',
            error_message='failed',
        )

        with patch('client_agents.models.AgentTask.objects.get', return_value=task):
            completed = service.schedule(data, parent_data=None)

        self.assertFalse(completed)
        self.assertEqual(data._outputs['result'], {})

    def test_splice_can_read_result_field(self):
        resolved = ConstantTemplate.resolve_template('${result["file_name"]}', {'result': {'file_name': 'demo.apk'}})
        self.assertEqual(resolved, 'demo.apk')


class BuildAndroidTests(SimpleTestCase):
    @patch('tasknexus_gem.entries.client.build.build_android.gen_uuid', return_value='guid-1')
    @patch('tasknexus_gem.entries.client.build.build_android.run')
    def test_main_returns_file_name_in_result(self, mock_run, _mock_uuid):
        with patch.dict(
            os.environ,
            {
                'package_type': 'default',
                'branch': 'feature/test',
                'build_env': 'prod',
            },
            clear=False,
        ):
            result = build_android.main()

        self.assertIsInstance(result, dict)
        self.assertIn('file_name', result)
        self.assertTrue(result['file_name'].endswith('.apk'))
        self.assertIn('feature_test', result['file_name'])

        run_args = mock_run.call_args.args[0]
        file_name_index = run_args.index('-fileName') + 1
        self.assertEqual(run_args[file_name_index], result['file_name'])
