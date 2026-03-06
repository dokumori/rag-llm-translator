"""
Unit Test: Translation Runner
-----------------------------
Tests the batch translation orchestrator in `services/toolbox/src/translate_runner.py`.
Verifies file discovery, batching, and API interaction logic.

Run Command:
    docker compose run --rm toolbox python -m pytest /app/tests/unit/test_translate_runner.py
"""
import translate_runner
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# Ensure we can import translate_runner from the services directory
# Ensure we can import translate_runner from the services directory
# sys.path hacking removed per refactoring - rely on PYTHONPATH


class TestTranslateRunner(unittest.TestCase):

    # --- Tests for find_po_files ---

    @patch('translate_runner.glob.glob')
    def test_find_po_files(self, mock_glob):
        """Test finding .po files recursively."""
        # Setup mock return
        mock_files = ['/input/file1.po', '/input/sub/file2.po']
        mock_glob.return_value = mock_files

        # Execute
        result = translate_runner.find_po_files('/input')

        # Verify
        mock_glob.assert_called_once_with(
            os.path.join('/input', "**/*.po"), recursive=True)
        self.assertEqual(result, mock_files)

    @patch('translate_runner.glob.glob')
    def test_find_po_files_empty(self, mock_glob):
        """Test finding no files."""
        mock_glob.return_value = []
        result = translate_runner.find_po_files('/input')
        self.assertEqual(result, [])

    # --- Tests for prepare_command ---

    def test_prepare_command(self):
        """Test command argument construction."""
        model = "test-model"
        lang = "ja"
        folder = "/tmp/folder"

        cmd = translate_runner.prepare_command(model, lang, folder)

        expected_cmd = [
            sys.executable,
            "-m", "python_gpt_po.main",
            "--provider", "openai",
            "--model", model,
            "--folder", folder,
            "--lang", lang,
            "--bulk",
            "--bulksize", "15"
        ]
        self.assertEqual(cmd, expected_cmd)

    # --- Tests for execute_translation (Retries) ---

    @patch('translate_runner.subprocess.run')
    @patch('translate_runner.time.sleep')
    def test_execute_translation_success_first_try(self, mock_sleep, mock_run):
        """Test successful execution on the first attempt."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        cmd = ["echo", "test"]
        env = {}

        result = translate_runner.execute_translation(cmd, env)

        self.assertEqual(result.returncode, 0)
        mock_run.assert_called_once_with(
            cmd, env=env, capture_output=True, text=True
        )
        mock_sleep.assert_not_called()

    @patch('translate_runner.subprocess.run')
    @patch('translate_runner.time.sleep')
    def test_execute_translation_retry_success(self, mock_sleep, mock_run):
        """Test execution fails once, then succeeds."""
        fail_res = MagicMock()
        fail_res.returncode = 1
        fail_res.stderr = "Mock Error"

        success_res = MagicMock()
        success_res.returncode = 0

        mock_run.side_effect = [fail_res, success_res]

        cmd = ["echo", "test"]
        env = {}

        result = translate_runner.execute_translation(cmd, env, max_retries=1)

        # Assert success and verify it took 2 attempts (initial + 1 retry)
        # The sleep mock confirms we waited between attempts.
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        # Assertion: Verify backoff logic (2 ** 1 = 2 seconds)
        mock_sleep.assert_called_with(2)

    @patch('translate_runner.subprocess.run')
    @patch('translate_runner.time.sleep')
    def test_execute_translation_final_failure(self, mock_sleep, mock_run):
        """Test execution fails after all retries."""
        fail_res = MagicMock()
        fail_res.returncode = 1
        fail_res.stderr = "Final Error"
        mock_run.return_value = fail_res

        cmd = ["echo", "test"]
        env = {}

        result = translate_runner.execute_translation(cmd, env, max_retries=1)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(mock_run.call_count, 2)  # Initial + 1 retry

    # --- Tests for Workflow & Isolation Logic ---

    @patch('translate_runner.os.makedirs')
    @patch('translate_runner.shutil.copy2')
    @patch('translate_runner.os.path.exists')
    @patch('translate_runner.os.path.isfile')
    @patch('translate_runner.os.path.getsize')
    @patch('translate_runner.glob.glob')
    @patch('translate_runner.execute_translation')
    @patch('translate_runner.tempfile.TemporaryDirectory')
    def test_run_translation_workflow_isolation_and_success(self, mock_temp, mock_exec, mock_glob, mock_getsize, mock_isfile, mock_exists, mock_copy, mock_mkdirs):
        """
        Verify isolation logic:
        1. Context manager creates temp dir.
        2. Copies src -> temp.
        3. Runs command.
        4. Copies temp -> dest (on success).
        """
        # Setup Temp Dir Context
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = "/tmp/mock_work"
        mock_temp.return_value = mock_ctx

        # Setup Files Found (First glob call)
        # Subsequent glob calls will be for cleaning temp dir
        def glob_side_effect(*args, **kwargs):
            if "input" in args[0]:
                return ['/input/file1.po']
            elif "mock_work" in args[0]:  # Cleaning step
                return ['/tmp/mock_work/garbage.txt']
            return []
        mock_glob.side_effect = glob_side_effect

        # Setup Execution Success
        # Mock subprocess.run to return exit code 0 (success)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_exec.return_value = mock_res

        # Setup File Existence (Output file check)
        mock_exists.side_effect = lambda p: p in ('/tmp/mock_work/file1.po', '/input/file1.po')
        mock_isfile.side_effect = lambda p: p == '/tmp/mock_work/file1.po'
        mock_getsize.side_effect = lambda p: 100 if p == '/tmp/mock_work/file1.po' else 0

        # Execute
        translate_runner.run_translation_workflow("model", "/input", "/output")

        # Verify 1: Copy to Temp
        mock_copy.assert_any_call('/input/file1.po', '/tmp/mock_work/file1.po')

        # Verify 3: Copy to Final Destination (Result was 0)
        mock_copy.assert_any_call(
            '/tmp/mock_work/file1.po', '/output/file1.po')

    @patch('translate_runner.shutil.copy2')
    @patch('translate_runner.os.path.exists')
    @patch('translate_runner.os.path.isfile')
    @patch('translate_runner.os.path.getsize')
    @patch('translate_runner.glob.glob')
    @patch('translate_runner.execute_translation')
    @patch('translate_runner.tempfile.TemporaryDirectory')
    @patch('translate_runner.os.makedirs')
    def test_run_translation_workflow_missing_output(self, mock_mkdirs, mock_temp, mock_exec, mock_glob, mock_getsize, mock_isfile, mock_exists, mock_copy):
        """Test case where tool succeeds (exit 0) but output file is missing."""
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = "/tmp/mock_work"
        mock_temp.return_value = mock_ctx

        # Only return input file, empty list for cleanup glob
        mock_glob.side_effect = lambda p, **k: [
            '/input/file1.po'] if 'input' in p else []

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_exec.return_value = mock_res

        # Condition: Source file exists? Yes. Output file exists? No.
        # The code calls os.path.exists(temp_file_path) for the output check.
        # It assumes src exists implicitly via glob.
        mock_exists.side_effect = lambda p: p == '/input/file1.po'  # Output file missing
        mock_isfile.side_effect = lambda p: p == '/input/file1.po'
        mock_getsize.side_effect = lambda p: 100 if p == '/input/file1.po' else 0

        # Execute
        translate_runner.run_translation_workflow("model", "/input", "/output")

        # Verify: NO copy to output
        # Check all copy calls, ensure none target /output
        for call_args in mock_copy.call_args_list:
            args, _ = call_args
            dest = args[1]
            self.assertNotIn(
                '/output', dest, "Should not copy to output if file is missing")


if __name__ == '__main__':
    unittest.main()
