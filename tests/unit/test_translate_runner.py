import os
import pytest
from unittest.mock import patch, MagicMock
import sys

# Add src to python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/toolbox/src')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/shared/src')))

from translate_runner import (
    check_dry_run,
    generate_output_filepath,
    validate_output_file,
    process_single_file,
    TranslationContext
)

@pytest.mark.parametrize("mock_return, expected", [
    ([{"id": "model_a", "is_dry_run": True}], True),
    ([{"id": "model_a", "is_dry_run": False}], False),
    ([{"id": "model_a"}], False),
    ([{"id": "other_model", "is_dry_run": True}], False),
])
@patch('translate_runner.load_models_config')
def test_check_dry_run(mock_load_models_config, mock_return, expected):
    """
    Tests check_dry_run with various model configurations.
    Ensures correct boolean return based on 'is_dry_run' presence and value.
    """
    mock_load_models_config.return_value = mock_return
    assert check_dry_run("model_a") is expected

@patch('translate_runner.load_models_config')
def test_check_dry_run_exception(mock_load_models_config):
    """
    Tests check_dry_run's error handling.
    Ensures it returns False and doesn't crash when config loading fails.
    """
    mock_load_models_config.side_effect = Exception("Config error")
    assert check_dry_run("model_a") is False

def test_generate_output_filepath():
    """
    Tests the filename generation logic.
    Ensures naming convention matches {basename}_{slug}_{mode}_{timestamp}.{ext}
    """
    expected_path = os.path.join("output_dir", "test_file_slug1_ragX_2026.po")
    actual_path = generate_output_filepath("output_dir", "test_file.po", "slug1", "ragX", "2026")
    assert actual_path == expected_path

def test_validate_output_file(tmp_path):
    """
    Tests exhaustive validation of the output file.
    Covers: non-existence, directory collision, empty file, and valid file.
    """
    temp_dir = str(tmp_path)
    file_path = os.path.join(temp_dir, "test.po")

    # State 1: file does not exist
    assert validate_output_file(file_path) is False

    # State 2: path is a directory (unlikely but possible error state)
    os.makedirs(file_path)
    assert validate_output_file(file_path) is False
    os.rmdir(file_path) # Clean up for next state

    # State 3: file exists but is empty (0 bytes)
    with open(file_path, 'w') as f:
        pass
    assert validate_output_file(file_path) is False

    # State 4: file is valid and has content
    with open(file_path, 'w') as f:
        f.write("content")
    assert validate_output_file(file_path) is True

@patch('translate_runner.execute_translation')
@patch('translate_runner.prepare_command')
def test_process_single_file_success(mock_prepare, mock_execute, tmp_path):
    """
    Tests a successful end-to-end file translation process.
    Mocks the translation execution and verifies the file is correctly
    copied to the final destination with the expected name.
    """
    input_base_dir = tmp_path / "input"
    output_base_dir = tmp_path / "output"
    input_base_dir.mkdir()
    output_base_dir.mkdir()

    src_file = input_base_dir / "test.po"
    src_file.write_text("original content")

    ctx = TranslationContext(
        model="model", target_lang="ja", env={"OPENAI_API_KEY": "dummy"},
        model_slug="slug", rag_mode="rag", timestamp="ts"
    )

    # Mock success. Because shutil.copy2 copies the original content to the temp path
    # before execute_translation is called, the file will exist and have non-zero size,
    # so `validate_output_file` will correctly pass without needing a mock!
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_execute.return_value = mock_result

    success = process_single_file(str(src_file), str(output_base_dir), ctx)

    assert success is True
    
    final_output = output_base_dir / "test_slug_rag_ts.po"
    assert final_output.exists()
    assert final_output.read_text() == "original content"

@patch('translate_runner.execute_translation')
@patch('translate_runner.prepare_command')
def test_process_single_file_failure(mock_prepare, mock_execute, tmp_path):
    """
    Tests the failure path of the single file translation process.
    Ensures that when translation fails, the function returns False and
    no file is moved to the final output directory.
    """
    input_base_dir = tmp_path / "input"
    output_base_dir = tmp_path / "output"
    input_base_dir.mkdir()
    output_base_dir.mkdir()

    src_file = input_base_dir / "test.po"
    src_file.write_text("original content")

    ctx = TranslationContext(
        model="model", target_lang="ja", env={"OPENAI_API_KEY": "dummy"},
        model_slug="slug", rag_mode="rag", timestamp="ts"
    )

    # Mock failure
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_execute.return_value = mock_result

    success = process_single_file(str(src_file), str(output_base_dir), ctx)

    assert success is False
    
    final_output = output_base_dir / "test_slug_rag_ts.po"
    assert not final_output.exists()
