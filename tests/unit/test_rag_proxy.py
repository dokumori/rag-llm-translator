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

# sys.path is configured via pytest.ini (pythonpath). The Docker-side path is
# kept as a fallback so the file can also be run directly inside the container.
sys.path.append("/app/services/rag-proxy/src")

# app.py runs _validate_embedding_model_consistency() at import time, which
# tries to reach ChromaDB. Patch all three external touch-points BEFORE the
# import so the startup side-effects are completely suppressed in unit tests.
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
    assert result == [{"text": "Hello", "context": ""}, {"text": "World", "context": ""}]


def test_parse_input_payload_sliding_window_noise():
    """Test extracting JSON array from noisy text."""
    source_text = 'Some chatter... [ "Item 1", "Item 2" ] trailing noise'
    result = app.parse_input_payload(source_text)
    assert result == [{"text": "Item 1", "context": ""}, {"text": "Item 2", "context": ""}]


def test_parse_input_payload_nested_brackets():
    """Test extraction with multiple brackets, should find the last valid array."""
    # Logic in app.py iterates reversed(start_indices).
    # It tries to parse from each '[' to the end.

    # Case: valid array at end
    source_text = 'ignore [ this ] and [ "Valid" ]'
    result = app.parse_input_payload(source_text)
    assert result == [{"text": "Valid", "context": ""}]


def test_parse_input_payload_broken_json_fallback():
    """Test fallback to treating input as single string if JSON fails."""
    source_text = 'Just a normal sentence.'
    result = app.parse_input_payload(source_text)
    assert result == [{"text": "Just a normal sentence.", "context": ""}]


def test_parse_input_payload_delimiter_stripping():
    """Test removal of 'Text to translate:' prefix."""
    # Use proper JSON quotes
    source_text = '["Text to translate:\\nHello"]'
    result = app.parse_input_payload(source_text)
    assert result == [{"text": "Hello", "context": ""}]

# --- global_context extraction tests ---
# These tests verify that context values carried inside dict items are correctly
# extracted, regardless of surrounding prompt prose.


def test_parse_input_payload_global_context_applied_to_all_strings():
    """
    When po_translator sends a batch where all items share the same msgctxt,
    each dict item carries that context explicitly.
    """
    import json
    items = [{"text": "String A", "context": "context1"}, {"text": "String B", "context": "context1"}]
    source_text = "Translate the following:\n" + json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert len(result) == 2
    assert result[0] == {"text": "String A", "context": "context1"}
    assert result[1] == {"text": "String B", "context": "context1"}


def test_parse_input_payload_no_context_prefix_yields_empty_context():
    """
    When po_translator sends a batch with no msgctxt, context is the empty string.
    """
    import json
    items = [{"text": "String without context", "context": ""}]
    source_text = "Translate the following:\n" + json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert len(result) == 1
    assert result[0] == {"text": "String without context", "context": ""}


def test_parse_input_payload_dict_item_context_takes_priority_over_global():
    """
    Each dict item owns its context value independently.
    An item with "context": "" stays empty; an item with a value keeps it.
    """
    import json
    items = [{"text": "Hello", "context": "item_ctx"}, {"text": "World", "context": ""}]
    source_text = json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert result[0]["context"] == "item_ctx"
    assert result[1]["context"] == ""


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
        'documents': [['source phrase']],
        'distances': [[0.1]],
        'metadatas': [[{'target': 'target phrase'}]]
    }

    # Mock TM response (empty for this test to focus on glossary)
    mock_tm.query.return_value = {
        'documents': [[]],
        'distances': [[]],
        'metadatas': [[]]
    }

    query = [{"text": "source phrase"}]
    content, logs = app.perform_rag_lookup(query)

    assert "target phrase" in content
    # Verify the reference-data framing delimiters are present when content is found.
    # If the `if rag_content:` block were removed, raw content would appear without
    # framing and these assertions would catch the regression.
    assert "[REFERENCE DATA" in content
    assert "[END REFERENCE DATA]" in content
    # Look for the glossary log entry
    glossary_log = next((l for l in logs if l['type'] == 'glossary'), None)

    # Assert that the match was ACCEPTED because distance (0.1) < threshold (0.25)
    # and "target phrase" was successfully injected into the context.
    assert glossary_log is not None
    assert glossary_log['accepted'] is True
    assert glossary_log['dist'] == 0.1
    assert glossary_log['no_shared_words'] is False


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
        'documents': [['something else']],
        'distances': [[0.8]],
        'metadatas': [[ {'target': 'no match'}]]
    }

    query = [{"text": "my query"}]

    content, logs = app.perform_rag_lookup(query)

    # Assert "target phrase" is NOT in content (suppressed)
    # and log shows accepted=False due to high distance (0.8).
    assert "target phrase" not in content
    assert logs[0]['accepted'] is False
    assert logs[0]['dist'] == 0.8
    # No accepted content → framing delimiters must be absent (empty string returned).
    assert "[REFERENCE DATA" not in content


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
        'documents': [['banana']],
        'distances': [[0.2]],
        'metadatas': [[{'target': 'fruit'}]]
    }

    query = [{"text": "apple"}]
    content, logs = app.perform_rag_lookup(query)

    assert logs[0]['accepted'] is False
    assert logs[0]['no_shared_words'] is True


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
        'documents': [['hi']],
        'distances': [[0.05]],
        'metadatas': [[{'target': 'hello'}]]
    }

    query = [{"text": "greeting"}]  # 'greeting' vs 'hi' no word overlap
    content, logs = app.perform_rag_lookup(query)

    assert logs[0]['accepted'] is True
    assert logs[0]['no_shared_words'] is True

    
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

        mock_g.query.return_value = {'documents': [[]], 'distances': [[]], 'metadatas': [[]]}
        mock_t.query.return_value = {'documents': [[]], 'distances': [[]], 'metadatas': [[]]}
        mock_client.get_collection.side_effect = lambda name, embedding_function=None: mock_g if name == "env_glossary" else mock_t
        
        # Call function

        app.perform_rag_lookup([{"text": "test"}])
        
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

def test_models_config_returns_model_list():
    """
    Verify that get_models_config delegates to load_models_config and returns
    the expected list of model dicts.

    Note: get_models_config is intentionally NOT cached so that edits to
    config/models/custom/models.json are picked up without restarting the
    container.  The test therefore does not assert on caching behaviour.
    """
    mock_models = [{"id": "test-model"}]

    with patch("app.load_models_config", return_value=mock_models):
        result = app.get_models_config()

    assert result == mock_models
    assert result[0]["id"] == "test-model"


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
    mock_parse.return_value = [{"text": "Parsed Query"}]
    mock_rag.return_value = ("<tm_matches>...</tm_matches>", [])

    # Mock OpenAI Response
    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {
        "choices": [{"message": {"content": "Translated Text"}}]
    }
    # Wire up choices explicitly so the app's finish_reason and content reads
    # return real values rather than opaque MagicMock objects.
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = "Translated Text"
    mock_completion.choices = [mock_choice]
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


# --- Part 3b: call_kwargs Construction Tests ---
# These tests pin the exact upstream API call parameters (temperature,
# max_tokens / max_completion_tokens) for both standard and OpenAI reasoning
# models to guard against regressions.
#
# OpenAI reasoning models (o1, o3, o4, gpt-5) have two constraints:
#   1. They reject temperature values other than 1 with a 400 error.
#   2. They require max_completion_tokens instead of max_tokens.
# We handle both explicitly — we do NOT rely on LiteLLM to translate them.


@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_real_call_includes_temperature_by_default(mock_config, mock_rag, mock_get_client, client):
    """Standard models (no flags) must receive temperature=0 in the API call."""
    mock_config.return_value = [{"id": "standard-model", "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": "standard-model",
        "messages": [{"role": "user", "content": "hello"}],
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "temperature" in call_kwargs, "temperature must be present for standard models"
    assert call_kwargs["temperature"] == 0


@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_real_call_uses_max_tokens_by_default(mock_config, mock_rag, mock_get_client, client):
    """Standard models (no flags) must receive max_tokens, not max_completion_tokens."""
    mock_config.return_value = [{"id": "standard-model", "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": "standard-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 500,
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "max_tokens" in call_kwargs, "max_tokens must be present for standard models"
    assert call_kwargs["max_tokens"] == 500
    assert "max_completion_tokens" not in call_kwargs, "max_completion_tokens must be absent"


@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_o_series_model_omits_temperature(mock_config, mock_rag, mock_get_client, client):
    """
    O-series reasoning models (o1, o3, o4) and GPT-5 family models only
    support temperature=1 and reject temperature=0 with a 400 error.  The
    proxy must omit temperature entirely for those models.

    Regression test for: o3-mini 400 UnsupportedParamsError bug.
    """
    mock_config.return_value = [{"id": "o3-mini", "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": "o3-mini",
        "messages": [{"role": "user", "content": "hello"}],
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "temperature" not in call_kwargs, (
        "temperature must NOT be sent to O-series models — they only accept temperature=1 "
        "and will reject any other value with a 400 error"
    )


@pytest.mark.parametrize("model_id", [
    "o1",
    "o1-mini",
    "o1-preview",
    "o3-mini",
    "o3",
    "o4-mini",
    "gpt-5",
    "gpt-5.5",
])
@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_all_o_series_prefixes_omit_temperature(mock_config, mock_rag, mock_get_client, model_id, client):
    """
    Parametrized check: every known O-series model ID must have temperature
    omitted from the upstream API call.
    """
    mock_config.return_value = [{"id": model_id, "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": model_id,
        "messages": [{"role": "user", "content": "hello"}],
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "temperature" not in call_kwargs, (
        f"temperature must NOT be sent to O-series model '{model_id}'"
    )


@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_o_series_model_uses_max_completion_tokens(mock_config, mock_rag, mock_get_client, client):
    """
    O-series reasoning models must receive max_completion_tokens (not max_tokens)
    in the upstream API call.  OpenAI will reject max_tokens with a 400 error
    for these models.  We do not rely on LiteLLM to translate this.

    Regression test for: o-series / GPT-5 max_tokens 400 error.
    """
    mock_config.return_value = [{"id": "o3-mini", "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": "o3-mini",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 1234,
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "max_completion_tokens" in call_kwargs, (
        "O-series models must receive max_completion_tokens, not max_tokens"
    )
    assert call_kwargs["max_completion_tokens"] == 1234
    assert "max_tokens" not in call_kwargs, (
        "max_tokens must NOT be sent to O-series models — OpenAI will reject it with a 400 error"
    )


@pytest.mark.parametrize("model_id", [
    "o1",
    "o1-mini",
    "o1-preview",
    "o3-mini",
    "o3",
    "o4-mini",
    "gpt-5",
    "gpt-5.5",
])
@patch('app.get_upstream_client')
@patch('app.perform_rag_lookup')
@patch('app.get_models_config')
def test_all_o_series_prefixes_use_max_completion_tokens(
    mock_config, mock_rag, mock_get_client, model_id, client
):
    """
    Parametrized check: every known O-series / GPT-5 model ID must use
    max_completion_tokens (not max_tokens) in the upstream API call.
    """
    mock_config.return_value = [{"id": model_id, "is_dry_run": False}]
    mock_rag.return_value = ("", [])

    mock_openai = MagicMock()
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai.chat.completions.create.return_value = mock_completion
    mock_get_client.return_value = mock_openai

    client.post('/v1/chat/completions', json={
        "model": model_id,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 999,
    })

    call_kwargs = mock_openai.chat.completions.create.call_args[1]
    assert "max_completion_tokens" in call_kwargs, (
        f"max_completion_tokens must be present for O-series model '{model_id}'"
    )
    assert call_kwargs["max_completion_tokens"] == 999
    assert "max_tokens" not in call_kwargs, (
        f"max_tokens must NOT be sent to O-series model '{model_id}'"
    )


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
            'documents': [['source']],
            'distances': [[0.2]],
            'metadatas': [[{'target': 'target'}]]
        }

        content, logs = app.perform_rag_lookup([{"text": "test"}])
        
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
        'documents': [['Publish']],
        'distances': [[0.10]],
        'metadatas': [[{'target': '掲載する'}]]
    }

    query = [{"text": "publishing"}]
    content, logs = app.perform_rag_lookup(query)

    glossary_log = next((l for l in logs if l['type'] == 'glossary'), None)
    assert glossary_log is not None
    assert glossary_log['accepted'] is True
    assert "掲載する" in content


# --- Part 6: /api/ingest/languages Endpoint Tests ---


class TestIngestLanguagesEndpoint:
    """
    Unit tests for GET /api/ingest/languages.

    Verifies that the endpoint correctly discovers distinct language codes
    stored as metadata in the glossary and TM collections, and handles
    edge cases (missing collections, empty collections) gracefully.
    """

    @patch('app.get_chroma_client')
    def test_returns_correct_language_sets(self, mock_get_chroma, client):
        """Returns per-collection and union language sets from metadata."""
        mock_chroma = MagicMock()

        col_g = MagicMock()
        col_g.name = Config.GLOSSARY_COLLECTION
        col_t = MagicMock()
        col_t.name = Config.TM_COLLECTION

        mock_chroma.list_collections.return_value = [col_g, col_t]
        mock_chroma.get_collection.side_effect = (
            lambda name: col_g if name == Config.GLOSSARY_COLLECTION else col_t
        )

        # Glossary has ja + it (ja appears twice — deduplication required)
        col_g.get.return_value = {
            "metadatas": [
                {"langcode": "ja"},
                {"langcode": "it"},
                {"langcode": "ja"},
            ]
        }
        # TM has ja + de
        col_t.get.return_value = {
            "metadatas": [
                {"langcode": "ja"},
                {"langcode": "de"},
            ]
        }

        mock_get_chroma.return_value = mock_chroma

        response = client.get('/api/ingest/languages')

        assert response.status_code == 200
        data = response.get_json()
        assert data["glossary_langs"] == ["it", "ja"]          # sorted, deduplicated
        assert data["tm_langs"] == ["de", "ja"]                 # sorted
        assert data["all_langs"] == ["de", "it", "ja"]          # union, sorted

    @patch('app.get_chroma_client')
    def test_missing_collection_is_skipped_gracefully(self, mock_get_chroma, client):
        """If one collection does not exist in ChromaDB it is silently skipped."""
        mock_chroma = MagicMock()

        # Only the TM collection exists
        col_t = MagicMock()
        col_t.name = Config.TM_COLLECTION
        mock_chroma.list_collections.return_value = [col_t]
        mock_chroma.get_collection.return_value = col_t

        col_t.get.return_value = {"metadatas": [{"langcode": "fr"}]}

        mock_get_chroma.return_value = mock_chroma

        response = client.get('/api/ingest/languages')

        assert response.status_code == 200
        data = response.get_json()
        assert data["glossary_langs"] == []       # glossary absent → empty
        assert data["tm_langs"] == ["fr"]
        assert data["all_langs"] == ["fr"]

    @patch('app.get_chroma_client')
    def test_empty_collections_return_empty_lists(self, mock_get_chroma, client):
        """Collections that exist but hold no documents return empty lang lists."""
        mock_chroma = MagicMock()

        col_g = MagicMock()
        col_g.name = Config.GLOSSARY_COLLECTION
        col_t = MagicMock()
        col_t.name = Config.TM_COLLECTION

        mock_chroma.list_collections.return_value = [col_g, col_t]
        mock_chroma.get_collection.side_effect = (
            lambda name: col_g if name == Config.GLOSSARY_COLLECTION else col_t
        )

        col_g.get.return_value = {"metadatas": []}
        col_t.get.return_value = {"metadatas": []}

        mock_get_chroma.return_value = mock_chroma

        response = client.get('/api/ingest/languages')

        assert response.status_code == 200
        data = response.get_json()
        assert data["glossary_langs"] == []
        assert data["tm_langs"] == []
        assert data["all_langs"] == []


# --- Part 7: parse_input_payload — "string" key fallback  ---


def test_parse_input_payload_string_key_fallback():
    """External callers using 'string' instead of 'text' as the field name must be accepted."""
    import json
    items = [{"string": "Save", "context": "button"}]
    source_text = json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert len(result) == 1
    assert result[0] == {"text": "Save", "context": "button"}


def test_parse_input_payload_text_takes_priority_over_string():
    """When a caller provides both 'text' and 'string' keys, 'text' takes priority."""
    import json
    items = [{"text": "Primary", "string": "Fallback", "context": ""}]
    source_text = json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert result[0]["text"] == "Primary"


def test_parse_input_payload_string_key_empty_text():
    """When a caller sends an empty 'text' field alongside 'string', the parser falls back to 'string'."""
    import json
    items = [{"text": "", "string": "Fallback value", "context": ""}]
    source_text = json.dumps(items)
    result = app.parse_input_payload(source_text)
    assert result[0]["text"] == "Fallback value"


# --- Part 8: _query_with_context_fallback Direct Tests  ---


class TestQueryWithContextFallback:
    """
    Direct unit tests for ``_query_with_context_fallback``.

    This function has multiple fallback paths:
      1. Context-specific query succeeds → return results with context_was_used=True
      2. Context-specific empty → context-free fallback → return with context_was_used=False
      3. Both context-specific and context-free empty → lang-only fallback
      4. No batch_context → context-free query only
      5. No lang_filter → plain query (no metadata filters)
    """

    @staticmethod
    def _make_result(documents=None, distances=None, metadatas=None):
        """Build a ChromaDB-style result dict."""
        return {
            "documents": documents or [[]],
            "distances": distances or [[]],
            "metadatas": metadatas or [[]],
        }

    def test_context_specific_hit(self):
        """Path 1: context-filtered query returns documents → use them."""
        collection = MagicMock()
        collection.name = "test_col"
        collection.query.return_value = self._make_result(
            documents=[["source text"]],
            distances=[[0.1]],
            metadatas=[[{"target": "translated"}]],
        )

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter={"langcode": "ja"},
            batch_context="button",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is True
        assert result["documents"] == [["source text"]]
        # Should be called once (the context-specific query)
        assert collection.query.call_count == 1
        call_where = collection.query.call_args[1]["where"]
        assert {"msgctxt": "button"} in call_where["$and"]

    def test_context_specific_empty_falls_back_to_context_free(self):
        """Path 2: context-specific returns no docs → try context-free entries."""
        collection = MagicMock()
        collection.name = "test_col"

        # First call (context-specific) → empty; second (context-free) → hit
        collection.query.side_effect = [
            self._make_result(documents=[[]]),  # context-specific: empty
            self._make_result(                  # context-free: has data
                documents=[["ctx-free source"]],
                distances=[[0.15]],
                metadatas=[[{"target": "ctx-free target"}]],
            ),
        ]

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter={"langcode": "ja"},
            batch_context="some_ctx",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is False
        assert result["documents"] == [["ctx-free source"]]
        assert collection.query.call_count == 2

    def test_all_context_queries_empty_falls_back_to_lang_only(self):
        """Path 3: context-specific + context-free both empty → lang-only."""
        collection = MagicMock()
        collection.name = "test_col"

        lang_only_result = self._make_result(
            documents=[["lang-only source"]],
            distances=[[0.2]],
            metadatas=[[{"target": "lang-only target"}]],
        )

        collection.query.side_effect = [
            self._make_result(documents=[[]]),  # context-specific: empty
            self._make_result(documents=[[]]),  # context-free: empty
            lang_only_result,                   # lang-only: has data
        ]

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter={"langcode": "ja"},
            batch_context="missing_ctx",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is False
        assert result["documents"] == [["lang-only source"]]
        assert collection.query.call_count == 3

    def test_no_batch_context_queries_context_free_only(self):
        """Path 4: empty batch_context → restrict to context-free entries."""
        collection = MagicMock()
        collection.name = "test_col"
        collection.query.return_value = self._make_result(
            documents=[["no-ctx source"]],
            distances=[[0.12]],
            metadatas=[[{"target": "no-ctx target"}]],
        )

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter={"langcode": "ja"},
            batch_context="",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is False
        assert collection.query.call_count == 1
        call_where = collection.query.call_args[1]["where"]
        # Should filter for msgctxt=="" (context-free entries only)
        assert {"msgctxt": ""} in call_where["$and"]

    def test_no_lang_filter_queries_without_metadata(self):
        """Path 5: no lang_filter → plain query with no where clause."""
        collection = MagicMock()
        collection.name = "test_col"
        collection.query.return_value = self._make_result(
            documents=[["plain source"]],
            distances=[[0.05]],
            metadatas=[[{"target": "plain target"}]],
        )

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter=None,
            batch_context="anything",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is False
        assert collection.query.call_count == 1
        # Should NOT have a 'where' key
        assert "where" not in collection.query.call_args[1]

    def test_context_specific_query_error_falls_back(self):
        """If the context-specific query raises, fall back gracefully."""
        collection = MagicMock()
        collection.name = "test_col"

        collection.query.side_effect = [
            Exception("ChromaDB timeout"),      # context-specific: error
            self._make_result(                  # context-free: works
                documents=[["fallback"]],
                distances=[[0.1]],
                metadatas=[[{"target": "ok"}]],
            ),
        ]

        result, ctx_used = app._query_with_context_fallback(
            collection=collection,
            query_texts=["query"],
            lang_filter={"langcode": "ja"},
            batch_context="ctx",
            context_meta_key="msgctxt",
            target_lang="ja",
        )

        assert ctx_used is False
        assert result["documents"] == [["fallback"]]
