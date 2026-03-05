from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

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
