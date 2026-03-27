"""
Unit Test: RAG Proxy App Logic
------------------------------
Tests the Flask routes and internal logic of `services/rag-proxy/src/app.py` in isolation.
Uses pure mocking to verify request parsing, payload construction, and response formatting.

Run Command:
    docker compose exec rag-proxy pytest /app/tests/unit/test_rag_proxy.py
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, mock_open
import json
from core.config import Config

# Ensure we can import app
# Ensure we can import app
sys.path.append("/app/services/rag-proxy/src")

# Patch external dependencies BEFORE importing app to prevent side effects
# Patch external dependencies BEFORE importing app to prevent side effects
# We also need to patch the shared layer which app imports at top level
with patch('infrastructure.get_chroma_client'), \
        patch('infrastructure.get_embedding_function'), \
        patch('openai.OpenAI'):
    import app


@pytest.fixture
def client():
    app.app.config['TESTING'] = True
    with app.app.test_client() as client:
        yield client

# --- Part 1: parse_input_payload Tests ---


def test_parse_input_payload_happy_path():
    """Test standard list input."""
    source_text = '["Hello", "World"]'
    result = app.parse_input_payload(source_text)
    assert result == ["Hello", "World"]


def test_parse_input_payload_sliding_window_noise():
    """Test extracting JSON array from noisy text."""
    source_text = 'Some chatter... [ "Item 1", "Item 2" ] trailing noise'
    result = app.parse_input_payload(source_text)
    assert result == ["Item 1", "Item 2"]


def test_parse_input_payload_nested_brackets():
    """Test extraction with multiple brackets, should find the last valid array."""
    # Logic in app.py iterates reversed(start_indices).
    # It tries to parse from each '[' to the end.

    # Case: valid array at end
    source_text = 'ignore [ this ] and [ "Valid" ]'
    result = app.parse_input_payload(source_text)
    assert result == ["Valid"]


def test_parse_input_payload_broken_json_fallback():
    """Test fallback to treating input as single string if JSON fails."""
    source_text = 'Just a normal sentence.'
    result = app.parse_input_payload(source_text)
    assert result == ["Just a normal sentence."]


def test_parse_input_payload_delimiter_stripping():
    """Test removal of 'Text to translate:' prefix."""
    # Use proper JSON quotes
    source_text = '["Text to translate:\\nHello"]'
    result = app.parse_input_payload(source_text)
    assert result == ["Hello"]

# --- Part 2: perform_rag_lookup Tests ---


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_guardrail_acceptance(mock_get_ef, mock_get_chroma):
    """Test Guardrail Acceptance (Low distance, semantic match)."""
    # Setup Mocks
    mock_client = MagicMock()

    # Bug Fix: Properly mock collection names
    mock_glossary = MagicMock()
    mock_glossary.name = "app_glossary"

    mock_tm = MagicMock()
    mock_tm.name = "app_tm"

    mock_client.list_collections.return_value = [mock_glossary, mock_tm]

    # Mock get_collection to return the correct mock based on name
    def get_collection_side_effect(name, embedding_function=None):
        if name == "app_glossary":
            return mock_glossary
        elif name == "app_tm":
            return mock_tm
        return MagicMock()

    mock_client.get_collection.side_effect = get_collection_side_effect
    mock_get_chroma.return_value = mock_client

    # Mock Query Response
    # Dist 0.1 < 0.25 (Threshold) -> Should Accept
    # Bug Fix: Correct nested list structure for results
    mock_glossary.query.return_value = {
        'documents': [['passage: source phrase']],
        'distances': [[0.1]],
        'metadatas': [[{'target': 'target phrase'}]]
    }

    # Mock TM response (empty for this test to focus on glossary)
    mock_tm.query.return_value = {
        'documents': [[]],
        'distances': [[]],
        'metadatas': [[]]
    }

    query = ["source phrase"]
    content, logs = app.perform_rag_lookup(query)

    assert "target phrase" in content
    # Look for the glossary log entry
    glossary_log = next((l for l in logs if l['type'] == 'glossary'), None)

    # Assert that the match was ACCEPTED because distance (0.1) < threshold (0.25)
    # and "target phrase" was successfully injected into the context.
    assert glossary_log is not None
    assert glossary_log['accepted'] is True
    assert glossary_log['dist'] == 0.1


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_guardrail_rejection(mock_get_ef, mock_get_chroma):
    """Test Guardrail Rejection (High distance)."""
    mock_client = MagicMock()
    mock_glossary = MagicMock()
    mock_glossary.name = "app_glossary"

    mock_client.list_collections.return_value = [mock_glossary]
    mock_client.get_collection.return_value = mock_glossary
    mock_get_chroma.return_value = mock_client

    # Dist 0.8 > 0.25 -> Should Reject
    mock_glossary.query.return_value = {
        'documents': [['passage: something else']],
        'distances': [[0.8]],
        'metadatas': [[{'target': 'no match'}]]
    }

    query = ["my query"]

    content, logs = app.perform_rag_lookup(query)

    # Assert "target phrase" is NOT in content (suppressed)
    # and log shows accepted=False due to high distance (0.8).
    assert "target phrase" not in content
    assert logs[0]['accepted'] is False
    assert logs[0]['dist'] == 0.8


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_hallucination_rejection(mock_get_ef, mock_get_chroma):
    """Test Hallucination Rejection (Low distance but ZERO word overlap)."""
    mock_client = MagicMock()
    mock_glossary = MagicMock()
    mock_glossary.name = "app_glossary"

    mock_client.list_collections.return_value = [mock_glossary]
    mock_client.get_collection.return_value = mock_glossary
    mock_get_chroma.return_value = mock_client

    # Dist 0.2 < 0.25 (Looks good) BUT 'apple' vs 'banana' has 0 overlap.
    # Should reject unless dist < 0.08
    mock_glossary.query.return_value = {
        'documents': [['passage: banana']],
        'distances': [[0.2]],
        'metadatas': [[{'target': 'fruit'}]]
    }

    query = ["apple"]
    content, logs = app.perform_rag_lookup(query)

    assert logs[0]['accepted'] is False
    # Verify the log message printed? We can't easily assert print, but we check status.


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_synonym_exception(mock_get_ef, mock_get_chroma):
    """Test Synonym Exception (Extremely low distance < 0.08, even with 0 overlap)."""
    mock_client = MagicMock()
    mock_glossary = MagicMock()
    mock_glossary.name = "app_glossary"

    mock_client.list_collections.return_value = [mock_glossary]
    mock_client.get_collection.return_value = mock_glossary
    mock_get_chroma.return_value = mock_client

    # Dist 0.05 < 0.08 -> Should Accept even with no overlap
    mock_glossary.query.return_value = {
        'documents': [['passage: hi']],
        'distances': [[0.05]],
        'metadatas': [[{'target': 'hello'}]]
    }

    query = ["greeting"]  # 'greeting' vs 'hi' no word overlap
    content, logs = app.perform_rag_lookup(query)

    assert logs[0]['accepted'] is True

    assert logs[0]['accepted'] is True
    
# --- Part 4: Dynamic Configuration Tests (New Coverage) ---

@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_collection_name_overrides(mock_get_ef, mock_get_chroma):
    """Verify that collection names respect environment variables."""
    with patch.object(Config, 'GLOSSARY_COLLECTION', 'env_glossary'), \
         patch.object(Config, 'TM_COLLECTION', 'env_tm'):
        mock_client = MagicMock()
        mock_get_chroma.return_value = mock_client
        
        # Mock List to include our env-defined collections
        mock_g = MagicMock()
        mock_g.name = "env_glossary"
        mock_t = MagicMock()
        mock_t.name = "env_tm"
        mock_client.list_collections.return_value = [mock_g, mock_t]
        
        # Call function
        app.perform_rag_lookup(["test"])
        
        # Verify get_collection called with Env names
        calls = [c[0][0] for c in mock_client.get_collection.call_args_list]
        assert "env_glossary" in calls
        assert "env_tm" in calls

def test_prompt_fallback_logic():
    """Verify fallback to generic.md if language-specific prompts are missing."""
    target_lang = "fr"
    
    # Paths expected:
    # 1. custom/fr.md
    # 2. fr.md
    # 3. generic.md
    
    with patch("os.path.exists") as mock_exists, \
         patch("builtins.open", mock_open(read_data="Generic Content")) as mock_file:
         
        # Simulate: Custom missing, Lang missing, Generic exists
        # side_effect needs to handle the exact path structure which depends on PROMPTS_DIR
        # Easier: check if path ends with 'generic.md'
        def exists_side_effect(path):
            return path.endswith("generic.md")
            
        mock_exists.side_effect = exists_side_effect
        
        content = app.get_system_prompt_from_md(target_lang)
        
        assert content == "Generic Content"
        # Verify we tried to read the generic one
        args, _ = mock_file.call_args
        assert args[0].endswith("generic.md")

def test_prompt_caching():
    """
    Verify that get_system_prompt_from_md uses @functools.lru_cache to prevent 
    redundant disk I/O when the same language prompt is requested multiple times.
    """
    # 1. Clear the cache before the test to ensure a clean state
    app.get_system_prompt_from_md.cache_clear()
    
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data="Cached Content")) as mock_file:
         
        # 2. First call: The cache is empty, so it must read from the disk (call open())
        res1 = app.get_system_prompt_from_md("es")
        
        # 3. Second call: The arguments ("es") are identical, so it should return 
        # the value from memory WITHOUT calling open() again.
        res2 = app.get_system_prompt_from_md("es")
        
        assert res1 == "Cached Content"
        assert res2 == "Cached Content"
        
        # 4. Verify that despite two function calls, the file was only opened once.
        # (The production logic checks 3 paths, but breaks after finding the first one 
        # that exists, which is custom/es.md since os.path.exists is mocked True).
        assert mock_file.call_count == 1
        
        # 5. Third call: A different argument ("de") means a cache miss. 
        # It must hit the disk again.
        res3 = app.get_system_prompt_from_md("de")
        assert mock_file.call_count == 2

def test_models_config_caching():
    """
    Verify that get_models_config caches disk reads to prevent parsing the 
    models.json file on every single translation request.
    """
    # 1. Clear cache to isolate the test
    app.get_models_config.cache_clear()
    
    mock_json = '{"models": [{"id": "test-model"}]}'
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_json)) as mock_file:
         
        # 2. Call the function twice sequentially.
        res1 = app.get_models_config()
        res2 = app.get_models_config()
        
        assert len(res1) == 1
        assert res1[0]["id"] == "test-model"
        
        # 3. Assert that the underlying JSON file was only opened and read ONCE.
        assert mock_file.call_count == 1


# --- Part 3: handle_translation Tests ---


@patch('app.get_models_config')
def test_handle_translation_dry_run(mock_get_config, client):
    """Test Dry Run Mode."""
    mock_get_config.return_value = [
        {"id": "dry-run-model", "is_dry_run": True}]

    payload = {
        "model": "dry-run-model",
        "messages": [{"role": "user", "content": '["Test"]'}]
    }

    response = client.post('/v1/chat/completions', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert "[DRY RUN] Test" in data['choices'][0]['message']['content']


@patch('app.get_upstream_client')
@patch('app.parse_input_payload')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_handle_translation_real_call(mock_config, mock_rag, mock_parse, mock_get_client, client):
    """Test Real API Call path (Mocked)."""
    mock_config.return_value = [{"id": "real-model"}]
    mock_parse.return_value = ["Parsed Query"]
    mock_rag.return_value = ("<tm_matches>...</tm_matches>", [])

    # Mock OpenAI Response
    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {
        "choices": [{"message": {"content": "Translated Text"}}]
    }
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    payload = {
        "model": "real-model",
        "messages": [{"role": "user", "content": "Original"}]
    }

    response = client.post('/v1/chat/completions', json=payload)

    assert response.status_code == 200
    assert "Translated Text" in response.get_json(
    )['choices'][0]['message']['content']

    # Verify System Prompt Construction
    call_args = mock_openai.chat.completions.create.call_args
    messages_arg = call_args[1]['messages']
    system_msg = messages_arg[0]['content']
    assert "<tm_matches>" in system_msg  # RAG content injected


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_custom_thresholds(mock_get_ef, mock_get_chroma):
    """Verify that environment variables override default thresholds."""
    with patch.object(Config, 'TM_THRESHOLD', 0.1), \
         patch.object(Config, 'GLOSSARY_THRESHOLD', 0.1), \
         patch.object(Config, 'RAG_STRICT_DISTANCE_THRESHOLD', 0.05):
        # Reload the app module to re-read env vars (variables are read at function scope in perform_rag_lookup)
        # Note: In the current app.py implementation, thresholds are local variables, so they are read every time perform_rag_lookup runs.
        # This makes testing easier without reloading.

        mock_client = MagicMock()
        mock_glossary = MagicMock()
        mock_glossary.name = "app_glossary"

        mock_client.list_collections.return_value = [mock_glossary]
        mock_client.get_collection.return_value = mock_glossary
        mock_get_chroma.return_value = mock_client

        # Dist 0.2 would be accepted by default (0.25) but rejected by custom logic (0.1)
        mock_glossary.query.return_value = {
            'documents': [['passage: source']],
            'distances': [[0.2]],
            'metadatas': [[{'target': 'target'}]]
        }

        content, logs = app.perform_rag_lookup(["test"])
        
        # Should be rejected because 0.2 > 0.1
        assert logs[0]['accepted'] is False
        assert logs[0]['dist'] == 0.2


# --- Part 5: Stemming Guardrail Tests ---

class TestSimpleStem:
    """Unit tests for the simple_stem morphological helper."""

    def test_ing_suffix(self):
        assert app.simple_stem("publishing") == "publish"

    def test_ed_suffix(self):
        assert app.simple_stem("published") == "publish"

    def test_s_suffix(self):
        assert app.simple_stem("publishes") == "publish"

    def test_er_suffix(self):
        assert app.simple_stem("publisher") == "publish"

    def test_tion_suffix(self):
        assert app.simple_stem("publication") == "public"

    def test_ment_suffix(self):
        assert app.simple_stem("management") == "manag"

    def test_short_word_unchanged(self):
        """Words where stripping would leave fewer than 3 chars should be unchanged."""
        assert app.simple_stem("ed") == "ed"
        assert app.simple_stem("ing") == "ing"

    def test_no_suffix(self):
        assert app.simple_stem("publish") == "publish"
        assert app.simple_stem("cat") == "cat"


class TestHasSharedStems:
    """Unit tests for the has_shared_stems guardrail helper."""

    def test_exact_match(self):
        assert app.has_shared_stems("publish", "publish") is True

    def test_stem_match_ing(self):
        assert app.has_shared_stems("publishing", "Publish") is True

    def test_stem_match_ed(self):
        assert app.has_shared_stems("published", "Publishing") is True

    def test_no_match(self):
        assert app.has_shared_stems("apple", "banana") is False

    def test_partial_sentence(self):
        assert app.has_shared_stems("publishing/unpublishing.", "Unpublish") is True

    def test_partial_sentence2(self):
        assert app.has_shared_stems("publishing/unpublishing.", "Published") is True

    def test_case_insensitive(self):
        assert app.has_shared_stems("PUBLISHING", "publish") is True


@patch('app.get_chroma_client')
@patch('app.get_embedding_function')
def test_perform_rag_lookup_stem_match_acceptance(mock_get_ef, mock_get_chroma):
    """Test that the guardrail accepts 'publishing' vs 'Publish' via stem matching."""
    mock_client = MagicMock()
    mock_glossary = MagicMock()
    mock_glossary.name = "app_glossary"

    mock_client.list_collections.return_value = [mock_glossary]
    mock_client.get_collection.return_value = mock_glossary
    mock_get_chroma.return_value = mock_client

    # Dist 0.10 < 0.25 (threshold) AND stems match -> Should Accept
    mock_glossary.query.return_value = {
        'documents': [['passage: Publish']],
        'distances': [[0.10]],
        'metadatas': [[{'target': '掲載する'}]]
    }

    query = ["publishing"]
    content, logs = app.perform_rag_lookup(query)

    glossary_log = next((l for l in logs if l['type'] == 'glossary'), None)
    assert glossary_log is not None
    assert glossary_log['accepted'] is True
    assert "掲載する" in content

