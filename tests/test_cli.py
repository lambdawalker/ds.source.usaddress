import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_core import SOURCE, family
from test_formats import definition


class CLITests(unittest.TestCase):
    def test_full_workflow_and_invalid_range_error(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'source.json'
            source.write_text(json.dumps(SOURCE))
            data = root / 'addresses.jsonl'
            data.write_text(json.dumps(family().to_dict()) + '\n')
            fmt = root / 'format.json'
            fmt.write_text(json.dumps(definition().to_dict()))
            raw, index = str(root / 'raw.sqlite'), str(root / 'index.sqlite')
            def run(*args):
                return subprocess.run([sys.executable, '-m', 'usaddress_dataset', *args], capture_output=True, text=True)
            commands = [
                ('init', '--raw', raw),
                ('import-jsonl', '--raw', raw, '--input', str(data), '--source', str(source)),
                ('index', '--raw', raw, '--index', index, '--format', str(fmt)),
                ('metadata', '--raw', raw, '--index', index),
                ('describe', '--raw', raw, '--index', index),
                ('count', '--raw', raw, '--index', index, '--line', '0:40', '--line', '0:40'),
                ('query', '--raw', raw, '--index', index, '--line', '0:40', '--line', '0:40', '--count', '3', '--seed', '7')]
            for command in commands:
                result = run(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout)
            self.assertEqual(parsed['returned_count'], 3)
            failed = run('query', '--raw', raw, '--index', index, '--line', '50:10')
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn('Traceback', failed.stderr)
