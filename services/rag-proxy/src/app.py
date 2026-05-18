from flask import Flask, request, jsonify, Response
from openai import OpenAI
import os
import json
import time
import datetime
import re
from typing import List, Dict, Any, Tuple, Optional, Union
import logging
import functools
import snowballstemmer
from core.config import Config, load_models_config

# Initialize stemmer globally
_stemmer = snowballstemmer.stemmer('english')

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
# Silence chatty libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

app = Flask(__name__)

from infrastructure import get_chroma_client, get_embedding_function


@functools.lru_cache(maxsize=1)
def get_upstream_client() -> OpenAI:
    """Returns the cached OpenAI client, initialised at most once (thread-safe via lru_cache)."""
    return OpenAI(
        api_key=Config.LLM_API_TOKEN,
        base_url=Config.LLM_BASE_URL
    )


# --- Configuration Paths ---
DEFAULT_LANG = Config.TARGET_LANG

@functools.lru_cache(maxsize=32)
def get_system_prompt_from_md(target_lang: str = DEFAULT_LANG) -> str:
    """
    Retrieves the expert system prompt dynamically based on the target language.
    Priority:
    1. Custom Override: /app/config/prompts/custom/{lang}.md
    2. Language Default: /app/config/prompts/{lang}.md
    3. Global Fallback: /app/config/prompts/generic.md
    """
    paths_to_check = [
        os.path.join(Config.PROMPTS_DIR, "custom", f"{target_lang}.md"),
        os.path.join(Config.PROMPTS_DIR, f"{target_lang}.md"),
        os.path.join(Config.PROMPTS_DIR, "generic.md")
    ]

    for path in paths_to_check:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        logger.info(f"📄 Loaded system prompt from: {path}")
                        return content
            except Exception as e:
                logger.error(f"❌ Failed to read prompt file {path}: {e}")

    logger.warning("⚠️ No system prompt found! Using hardcoded fallback.")
    return "Ensure the translation sounds natural and professional in the target language. Adhere to Microsoft Localization Style Guide."

def get_models_config() -> List[Dict[str, Any]]:
    """
    Retrieves model configurations from the shared JSON file, with custom override support.
    Uses load_models_config() to merge config/models/models.json with config/models/custom/models.json.

    Not cached — the file is re-read on each call so that edits to
    config/models/custom/models.json are picked up without restarting
    the container.  At ~3 KB the I/O cost is negligible compared to
    the LLM API call that follows.
    """
    return load_models_config()


# Log configuration at startup
Config.log_config()

_UNCALIBRATED_SENTINEL = 0.4
if (
    Config.EMBEDDING_MODEL_NAME != Config.DEFAULT_EMBEDDING_MODEL
    and Config.TM_THRESHOLD == _UNCALIBRATED_SENTINEL
    and Config.GLOSSARY_THRESHOLD == _UNCALIBRATED_SENTINEL
):
    logger.warning(
        f"⚠️ Non-default embedding model in use ({Config.EMBEDDING_MODEL_NAME}) "
        f"but thresholds appear uncalibrated (TM={Config.TM_THRESHOLD}, "
        f"Glossary={Config.GLOSSARY_THRESHOLD}). "
        f"Calibrate before using in production — see docs/3_RAG_performance_analysis.md."
    )


def _validate_embedding_model_consistency() -> None:
    """
    Fail fast at startup if ChromaDB collections were ingested with a different
    embedding model than the one currently configured.

    This check runs BEFORE the app starts serving requests and uses SystemExit(1)
    rather than RuntimeError to guarantee termination even if callers catch broad
    exceptions (e.g. the try/except in perform_rag_lookup).
    """
    try:
        client = get_chroma_client()
        for col_name in [Config.GLOSSARY_COLLECTION, Config.TM_COLLECTION]:
            try:
                col = client.get_collection(col_name)
                stored_model = (col.metadata or {}).get("embedding_model")
                if stored_model and stored_model != Config.EMBEDDING_MODEL_NAME:
                    logger.critical(
                        f"\n\n"
                        f"❌ MODEL MISMATCH detected in collection '{col_name}'.\n"
                        f"   Ingested with : '{stored_model}'\n"
                        f"   Current config: '{Config.EMBEDDING_MODEL_NAME}'\n"
                        f"\n"
                        f"Vectors from different models are incompatible. "
                        f"Search results would be meaningless.\n"
                        f"\n"
                        f"To switch models safely:\n"
                        f"  bin/switch-embedding-model.sh {Config.EMBEDDING_MODEL_NAME}\n"
                        f"\n"
                        f"Or manually:\n"
                        f"  1. bin/manage-backup.sh --dump\n"
                        f"  2. bin/ingest.sh  → choose Reset\n"
                        f"  3. bin/download-model.sh {Config.EMBEDDING_MODEL_NAME}\n"
                        f"  4. docker compose up -d --force-recreate rag-proxy\n"
                        f"  5. bin/ingest.sh  → re-ingest\n"
                    )
                    raise SystemExit(1)
            except SystemExit:
                raise
            except Exception as e:
                # Collection doesn't exist yet — that's fine.
                # Log other unexpected errors (network, auth, corruption) at WARNING
                # so they don't disappear silently.
                if "does not exist" not in str(e).lower() and "notfound" not in type(e).__name__.lower():
                    logger.warning(f"⚠️ Could not check model metadata in '{col_name}': {e}")
    except SystemExit:
        raise
    except Exception as e:
        logger.warning(f"⚠️ Could not validate embedding model consistency: {e}")


_validate_embedding_model_consistency()

# --- Helper Functions ---

def parse_input_payload(source_text: str) -> List[Dict[str, str]]:
    """
    Extracts the content to be translated using the 'Sliding Window' JSON parsing logic.
    Returns a cleaned list of dictionary objects with 'text' and 'context'.

    The payload is expected to be a JSON array of {"text": ..., "context": ...} dicts
    as produced by po_translator.py. The sliding window handles any surrounding
    prose the LLM might have added before or after the array.
    """
    query_payload: List[Any] = []

    start_indices = [i for i, char in enumerate(source_text) if char == '[']

    for idx in reversed(start_indices):
        try:
            # Check 1: Try parsing from this bracket to the very end
            candidate = source_text[idx:]
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                query_payload = parsed
                break
        except json.JSONDecodeError:
            # Check 2: Try parsing from this bracket to the last ']'
            try:
                last_bracket = source_text.rfind(']')
                if last_bracket > idx:
                    candidate_trimmed = source_text[idx: last_bracket + 1]
                    parsed = json.loads(candidate_trimmed)
                    if isinstance(parsed, list):
                        query_payload = parsed
                        break
            except Exception:
                pass

    # Fallback: treat the whole message as a single plain-text item
    if not query_payload:
        query_payload = [{"text": source_text.strip(), "context": ""}]

    cleaned_payload: List[Dict[str, str]] = []
    for item in query_payload:
        if isinstance(item, dict):
            text = item.get("text", "") or item.get("string", "") or ""
            context = item.get("context", "")
        else:
            text = str(item)
            context = ""

        if text.startswith("Text to translate:\n"):
            text = text[len("Text to translate:\n"):]

        cleaned_payload.append({"text": text, "context": context})

    return cleaned_payload

def simple_stem(word: str) -> str:
    """Stems an English word using the Snowball (Porter2) algorithm."""
    return _stemmer.stemWord(word)

# Minimal stop words list to prevent TM guardrail bypass
STOP_WORDS = {
    "a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", 
    "by", "with", "of", "in", "is", "are", "was", "were", "be", "been", "being",
    "it", "this", "that", "these", "those", "we", "you", "they", "he", "she", "as"
}

def has_shared_stems(text_a: str, text_b: str) -> bool:
    """
    Checks whether two strings share at least one meaningful word stem,
    ignoring common stop words.
    """
    words_a = {w for w in re.findall(r'\w+', text_a.lower()) if w not in STOP_WORDS}
    words_b = {w for w in re.findall(r'\w+', text_b.lower()) if w not in STOP_WORDS}

    if not words_a or not words_b:
        return False

    # Fast path: exact word match
    if words_a.intersection(words_b):
        return True

    # Slow path: compare stems
    stems_a = {simple_stem(w) for w in words_a}
    stems_b = {simple_stem(w) for w in words_b}
    
    return len(stems_a.intersection(stems_b)) > 0




def _group_by_context(
    query_payload: List[Dict[str, str]],
    formatted_query: List[str],
) -> Dict[str, List[Tuple[int, str, str]]]:
    """Groups payload items by context string → [(batch_index, formatted_text, original_text)]."""
    groups: Dict[str, List[Tuple[int, str, str]]] = {}
    for i, item in enumerate(query_payload):
        ctx = item.get("context", "").strip()
        groups.setdefault(ctx, []).append((i, formatted_query[i], item.get("text", "")))
    return groups


def _query_with_context_fallback(
    collection: Any,
    query_texts: List[str],
    lang_filter: Optional[Dict],
    batch_context: str,
    context_meta_key: str,
    target_lang: str,
) -> Tuple[Any, bool]:
    """
    Runs a ChromaDB query respecting context isolation.

    Strategy:
      1. If batch_context is present, query with
         (langcode == target_lang AND <context_meta_key> == batch_context).
         If that returns no documents, fall back to context-free entries only.
      2. If batch_context is ABSENT (empty), query with
         (langcode == target_lang AND <context_meta_key> == "").
         This prevents context-specific entries from bleeding into no-context strings.
      3. If no lang_filter, query without any metadata filter.

    Returns (result, context_was_used: bool).
    """
    base_kwargs = {"query_texts": query_texts, "n_results": 1}

    if lang_filter and batch_context:
        # Pass 1: context-specific query
        ctx_kwargs = {**base_kwargs, "where": {"$and": [{"langcode": target_lang}, {context_meta_key: batch_context}]}}
        try:
            ctx_res = collection.query(**ctx_kwargs)
            has_any = any(doc_list for doc_list in ctx_res.get("documents", []))
            if has_any:
                logger.info(f"   🎯 [{collection.name}] Context-filtered query succeeded (context='{batch_context}')")
                return ctx_res, True
            else:
                logger.info(f"   ⚠️ [{collection.name}] Context-filtered query returned no results; falling back (context='{batch_context}')")
        except Exception as ctx_err:
            logger.warning(f"   ⚠️ [{collection.name}] Context-filtered query failed ({ctx_err}); falling back to lang-only filter")

        # Fallback: context-free entries only (safe to apply regardless of caller's context)
        ctx_free_kwargs = {**base_kwargs, "where": {"$and": [{"langcode": target_lang}, {context_meta_key: ""}]}}
        try:
            ctx_free_res = collection.query(**ctx_free_kwargs)
            has_any = any(doc_list for doc_list in ctx_free_res.get("documents", []))
            if has_any:
                logger.info(f"   ↩️  [{collection.name}] Context-free fallback succeeded (no '{batch_context}' entries found).")
                return ctx_free_res, False
            else:
                logger.info(f"   ⚠️ [{collection.name}] Context-free fallback returned no results; using lang-only filter.")
        except Exception as fb_err:
            logger.warning(f"   ⚠️ [{collection.name}] Context-free fallback failed ({fb_err}); using lang-only filter.")

        # Last resort: full lang-only filter (catches pre-isolation ingested entries)
        return collection.query(**{**base_kwargs, "where": lang_filter}), False

    elif lang_filter:
        # No batch_context: restrict to context-free entries to avoid cross-context bleed
        no_ctx_kwargs = {**base_kwargs, "where": {"$and": [{"langcode": target_lang}, {context_meta_key: ""}]}}
        try:
            no_ctx_res = collection.query(**no_ctx_kwargs)
            has_any = any(doc_list for doc_list in no_ctx_res.get("documents", []))
            if has_any:
                return no_ctx_res, False
            else:
                logger.info(f"   ⚠️ [{collection.name}] No context-free entries found; falling back to lang-only filter")
        except Exception as no_ctx_err:
            logger.warning(f"   ⚠️ [{collection.name}] Context-free query failed ({no_ctx_err}); falling back to lang-only filter")

        # Fallback: lang-only (catches entries ingested before context isolation was enforced)
        return collection.query(**{**base_kwargs, "where": lang_filter}), False
    else:
        return collection.query(**base_kwargs), False


def _process_collection(
    collection: Any,
    groups: Dict[str, List[Tuple[int, str, str]]],
    lang_filter: Optional[Dict],
    target_lang: str,
    context_meta_key: str,
    threshold: float,
    strict_threshold: float,
    result_type: str,
    format_fn: Any,
) -> Tuple[List[Dict[str, Any]], set]:
    """
    Queries one ChromaDB collection for all context groups, applies the guardrail,
    and returns (match_log_entries, accepted_formatted_strings).
    """
    matches_log: List[Dict[str, Any]] = []
    accepted: set = set()

    for item_context, group_items in groups.items():
        group_indices = [g[0] for g in group_items]
        group_formatted_texts = [g[1] for g in group_items]
        group_original_texts = [g[2] for g in group_items]

        res, ctx_used = _query_with_context_fallback(
            collection, group_formatted_texts, lang_filter,
            item_context, context_meta_key, target_lang,
        )

        if not res.get("documents"):
            continue

        for j, doc_list in enumerate(res["documents"]):
            if not doc_list:
                continue
            # Guard: ChromaDB should always return parallel lists, but defend
            # against a missing/empty distances or metadatas entry to avoid
            # IndexError being silently swallowed by perform_rag_lookup's broad
            # except handler (which would zero out all RAG context).
            if not res["distances"][j] or not res["metadatas"][j]:
                logger.warning(
                    "   ⚠️ Skipping result %d: distances or metadatas list is empty "
                    "(collection may be missing embeddings).", j
                )
                continue
            item_index = group_indices[j]
            query_text = group_original_texts[j]
            dist = res["distances"][j][0]
            src = doc_list[0]
            tgt = res["metadatas"][j][0].get("target", "")


            # Guardrail: reject if no shared stems unless distance is extremely low
            is_semantic_match = dist < threshold
            has_shared_words = has_shared_stems(query_text, src)

            if not has_shared_words and dist > strict_threshold:
                is_accepted = False
                logger.info(
                    f"   🛡️ {result_type.upper()} Guardrail Rejection: '{query_text}' vs '{src}' "
                    f"(Dist: {dist:.4f}, No shared words)"
                )
            else:
                is_accepted = is_semantic_match

            matches_log.append({
                "type": result_type,
                "item_index": item_index,
                "context": item_context if ctx_used else "",
                "untranslated_string": query_text,
                "rag_context": src,
                "tgt": tgt,
                "dist": dist,
                "accepted": is_accepted,
                "no_shared_words": not has_shared_words,
            })

            if is_accepted:
                accepted.add(format_fn(src, tgt))

    return matches_log, accepted


def perform_rag_lookup(query_payload: List[Dict[str, str]], target_lang: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    """
    Queries ChromaDB Glossary and TM collections, applies guardrail logic, and returns
    the XML-formatted context string and match logs for structured logging.

    When target_lang is provided, queries are filtered by langcode metadata
    so only context for the correct target language is retrieved.
    """
    matches_log: List[Dict[str, Any]] = []
    found_glossary: set = set()
    found_tm: set = set()

    try:
        client = get_chroma_client()
        existing_collections = [c.name for c in client.list_collections()]

        # Build per-item query strings (appends context for richer semantic retrieval)
        formatted_query = [
            f"{item.get('text', '').strip()} context: {item.get('context', '').strip()}"
            if item.get("context", "").strip()
            else item.get("text", "").strip()
            for item in query_payload
        ]

        lang_filter = {"langcode": target_lang} if target_lang else None
        groups = _group_by_context(query_payload, formatted_query)

        # Process Glossary
        if Config.GLOSSARY_COLLECTION in existing_collections:
            gloss_col = client.get_collection(
                Config.GLOSSARY_COLLECTION, embedding_function=get_embedding_function()
            )
            log_entries, accepted = _process_collection(
                collection=gloss_col, groups=groups, lang_filter=lang_filter,
                target_lang=target_lang, context_meta_key="context",
                threshold=Config.GLOSSARY_THRESHOLD,
                strict_threshold=Config.RAG_STRICT_DISTANCE_THRESHOLD,
                result_type="glossary",
                format_fn=lambda src, tgt: f"- '{src}' -> '{tgt}'",
            )
            matches_log.extend(log_entries)
            found_glossary.update(accepted)

        # Process Translation Memory (TM)
        if Config.TM_COLLECTION in existing_collections:
            tm_col = client.get_collection(
                Config.TM_COLLECTION, embedding_function=get_embedding_function()
            )
            log_entries, accepted = _process_collection(
                collection=tm_col, groups=groups, lang_filter=lang_filter,
                target_lang=target_lang, context_meta_key="msgctxt",
                threshold=Config.TM_THRESHOLD,
                strict_threshold=Config.RAG_STRICT_DISTANCE_THRESHOLD,
                result_type="tm",
                format_fn=lambda src, tgt: f"Source: {src}\nTarget: {tgt}",
            )
            matches_log.extend(log_entries)
            found_tm.update(accepted)

    except Exception as e:
        logger.error(f"⚠️ RAG Lookup skipped: {e}", exc_info=True)

    rag_content = ""
    if found_glossary:
        rag_content += "\n<glossary_matches>\n" + "\n".join(found_glossary) + "\n</glossary_matches>\n"
    if found_tm:
        rag_content += "\n<tm_matches>\n" + "\n".join(found_tm) + "\n</tm_matches>\n"

    return rag_content, matches_log




# Hard-coded output format contract.
# This is appended to *every* system prompt so the LLM always returns the
# JSON array that po_translator._parse_translations() expects, regardless
# of which language-specific .md file is loaded.
# item_count is threaded in at request time so the model is told the exact
# number of elements expected — preventing Haiku-class models from splitting
# a single long entry into two array items.
def _format_instruction(item_count: int) -> str:
    return (
        "\n\n## Output Format (MANDATORY)\n"
        f"Return ONLY a JSON array of translated strings with EXACTLY {item_count} element(s) "
        "— one translation per input, in the same order.\n"
        "Do NOT split a single input into multiple elements, even if it contains newlines.\n"
        "Do NOT wrap the array in markdown code fences.\n"
        "Do NOT add explanations, notes, or alternatives outside the array."
    )


def construct_system_prompt(original_system_data: Union[str, List[Dict[str, str]]], rag_content: str, target_lang: str, item_count: int = 0) -> str:
    """Combines instructions, RAG context, and original system message."""
    expert_instructions = get_system_prompt_from_md(target_lang)

    original_system = original_system_data
    if isinstance(original_system, list):
        original_system = " ".join([s.get('text', '')
                                   for s in original_system if 'text' in s])

    return (
        f"{expert_instructions}\n\n{rag_content}\n\n"
        f"## Additional Instructions:\n{original_system}"
        f"{_format_instruction(item_count)}"
    )

# --- Helper: Extract Language from Path ---

def _extract_lang_from_path(path: str) -> Optional[str]:
    """Extracts target language from URL path segment like /lang_it/."""
    match = re.search(r'/lang_([a-z]{2,5})(?:/|$)', path)
    return match.group(1) if match else None


# --- Routes ---

@app.route('/v1/models', methods=['GET'])
@app.route('/v1/skip_rag/models', methods=['GET'])
@app.route('/v1/lang_<target_lang_code>/models', methods=['GET'])
@app.route('/v1/lang_<target_lang_code>/skip_rag/models', methods=['GET'])
def list_models(target_lang_code: str = None) -> Response:
    """Returns a dynamic list of models from configuration."""
    config_models = get_models_config()
    return jsonify({
        "object": "list",
        "data": [
            {"id": m["id"], "object": "model", "owned_by": "llm-provider"}
            for m in config_models
        ]
    })


@app.route('/v1/chat/completions', methods=['POST'])
@app.route('/v1/skip_rag/chat/completions', methods=['POST'])
@app.route('/v1/lang_<target_lang_code>/chat/completions', methods=['POST'])
@app.route('/v1/lang_<target_lang_code>/skip_rag/chat/completions', methods=['POST'])
def handle_translation(target_lang_code: str = None) -> Union[Response, Tuple[Response, int]]:
    """Main endpoint for handling translation requests."""
    start_time = time.time()
    try:
        data = request.json
        messages = data.get('messages', [])
        requested_model = (data.get('model') or "dry-run-dummy").strip()

        log_entry: Dict[str, Any] = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "model": requested_model,
            "rag_matches": [],
            "input_text": []
        }

        user_messages = [m for m in messages if m.get('role') == 'user']
        if not user_messages:
            return jsonify({"choices": [{"message": {"content": "Ping"}}]})

        source_text = user_messages[-1].get('content', '')

        # --- 1. EXTRACT CONTENT FOR RAG ---
        query_payload = parse_input_payload(source_text)
        log_entry["input_text"] = query_payload
        log_entry["batch_size"] = len(query_payload)

        # --- 2. RAG LOOKUP ---
        skip_rag = 'skip_rag' in request.path or str(request.args.get('skip_rag', '')).lower() == 'true'
        rag_content = ""
        rag_matches = []
        
        target_lang = data.get('target_lang') or request.headers.get('X-Target-Lang') or _extract_lang_from_path(request.path) or DEFAULT_LANG
        if not target_lang:
            logger.warning("⚠️ No target language resolved from body, header, path, or env. RAG filtering will be disabled.")
        else:
            logger.info(f"🌐 Target language resolved to: {target_lang} (from: {'body' if data.get('target_lang') else 'header' if request.headers.get('X-Target-Lang') else 'path' if _extract_lang_from_path(request.path) else 'default'})")

        if not skip_rag:
            try:
                rag_content, rag_matches = perform_rag_lookup(query_payload, target_lang=target_lang)
                log_entry["rag_matches"] = rag_matches
            except Exception as e:
                log_entry["rag_error"] = str(e)
                logger.error(f"⚠️ RAG Lookup skipped: {e}", exc_info=True)
                # Non-critical, we proceed without RAG
        else:
            logger.info("⏩ Skipping RAG lookup as requested (`skip_rag` is true)")
            rag_content = "\n<!-- RAG Lookup Skipped -->\n"

        # --- 3. CONSTRUCT PROMPT ---
        final_system_content = construct_system_prompt(
            data.get('system', ""), rag_content, target_lang, item_count=len(query_payload))

        # --- 4. STRUCTURED LOGGING ---
        log_entry["system_prompt_length"] = len(final_system_content)
        logger.info(json.dumps(log_entry, ensure_ascii=False))

        # --- 4a. PREPARE PAYLOAD ---
        new_messages = [{"role": "system", "content": final_system_content}]
        new_messages += [m for m in messages if m.get('role') != 'system']

        logger.info(f"FINAL_PAYLOAD: {json.dumps({'model': requested_model, 'messages': new_messages}, ensure_ascii=False)}")

        # --- 5. DRY RUN CHECK ---
        model_meta = next((m for m in get_models_config()
                          if m["id"] == requested_model), None)
                          
        # Force dry run if:
        #   - the model is marked as dry_run
        #   - the model is not given
        #   - entirely unknown
        is_dry_run = model_meta.get("is_dry_run") if model_meta else True

        if is_dry_run:
            log_entry["action"] = "dry_run"
            mock_translations = [f"[DRY RUN] {item.get('text', '')}" for item in query_payload]
            content_return = json.dumps(mock_translations, ensure_ascii=False)
            return jsonify({
                "id": "dry-run",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": requested_model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content_return},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            })

        # --- 6. REAL API CALL ---

        try:
            # O-series reasoning models (o1, o3, o4) and GPT-5 family models
            # have two constraints that differ from standard models:
            #   1. They reject temperature values other than 1 with a 400 error.
            #   2. They use max_completion_tokens instead of max_tokens.
            # We do NOT rely on LiteLLM to translate these automatically — the
            # temperature assumption burned us before, so we handle both explicitly.
            _openai_reasoning_model_prefixes = ("o1", "o1-", "o3", "o3-", "o4", "o4-", "gpt-5")
            _is_openai_reasoning_model = any(requested_model.lower().startswith(p) for p in _openai_reasoning_model_prefixes)

            output_token_limit = data.get("max_tokens", Config.LLM_MAX_TOKENS)
            call_kwargs: Dict[str, Any] = {
                "model": requested_model,
                "messages": new_messages,
            }
            if _is_openai_reasoning_model:
                call_kwargs["max_completion_tokens"] = output_token_limit
            else:
                call_kwargs["max_tokens"] = output_token_limit

            if not _is_openai_reasoning_model:
                call_kwargs["temperature"] = 0

            response = get_upstream_client().chat.completions.create(**call_kwargs)
            
            # --- API ERROR CHECKS ---
            for choice in response.choices:
                if choice.finish_reason in ["safety", "content_filter"]:
                    logger.warning(f"🚨 GUARDRAIL BLOCKED TRANSLATION! Finish Reason: {choice.finish_reason}")
                elif choice.finish_reason == "length":
                    limit = output_token_limit
                    logger.warning(
                        f"⚠️ RESPONSE TRUNCATED: the LLM stopped after generating {limit} output tokens "
                        "(this limit applies to the generated text, not the input). "
                        "The JSON response is likely cut off and parsing will fail. "
                        "To fix: lower BULK_SIZE in your .env to send fewer strings per request."
                    )
                elif not choice.message.content:
                    logger.warning(f"🚨 LLM RETURNED EMPTY STRING! Finish Reason: {choice.finish_reason}")
            
            raw_content = response.choices[0].message.content or ""
            sneak_peek = raw_content[:250].strip().replace('\n', ' ')
            logger.info(f"raw_output_sneak_peek: {sneak_peek}")
            # -----------------------------

            log_entry["processing_time"] = time.time() - start_time
            return jsonify(response.model_dump())
        except Exception as e:
            if hasattr(e, 'response'):
                code = getattr(e.response, 'status_code', 'Unknown')
                text = getattr(e.response, 'text', 'Unknown')
                logger.error(f"❌ API Error Code: {code}")
                logger.error(f"❌ API Error Body: {text}")
            logger.error(f"❌ Translation provider error: {e}", exc_info=True)
            return jsonify({"error": "Translation provider unavailable"}), 502

    except Exception as e:
        logger.error(f"❌ ERROR: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# --- RAG Lookup API ---
# Exposes perform_rag_lookup over HTTP so toolbox scripts (e.g. evaluate_blind_test.py)
# can retrieve RAG context without importing the rag-proxy's app module directly.

@app.route('/api/rag-lookup', methods=['POST'])
def api_rag_lookup() -> Union[Response, Tuple[Response, int]]:
    """
    Retrieves RAG context (glossary + TM matches) for a list of query items.

    Body:
        items (list[dict]): List of {"text": ..., "context": ...} dicts.
        target_lang (str, optional): Target language code for filtering.

    Returns:
        rag_context (str): The XML-formatted context string.
        matches (list[dict]): Detailed match log entries.
    """
    try:
        data = request.json or {}
        items = data.get("items", [])
        target_lang = data.get("target_lang", "")

        if not items:
            return jsonify({"error": "'items' is required"}), 400

        rag_context, matches = perform_rag_lookup(items, target_lang=target_lang)
        return jsonify({
            "rag_context": rag_context,
            "matches": matches,
        })
    except Exception as e:
        logger.error(f"❌ RAG lookup API failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# --- Ingestion API ---
# These endpoints let the toolbox delegate embedding + ChromaDB writes
# to the rag-proxy, keeping the toolbox image lightweight (no PyTorch/sentence-transformers).

@app.route('/api/ingest/reset', methods=['POST'])
def ingest_reset() -> Union[Response, Tuple[Response, int]]:
    """
    Resets a ChromaDB collection or deletes entries for a specific language.

    Body:
        collection (str): Collection name (e.g. "app_glossary", "app_tm").
        langcode (str): Language code. Use "all" to delete the entire collection.
    """
    try:
        data = request.json or {}
        collection_name = data.get("collection", "")
        langcode = data.get("langcode", "")

        if not collection_name or not langcode:
            return jsonify({"error": "Both 'collection' and 'langcode' are required"}), 400

        client = get_chroma_client()

        try:
            col = client.get_collection(collection_name)
            if langcode == "all":
                client.delete_collection(collection_name)
                logger.info(f"🗑️  Ingest API: Deleted entire collection '{collection_name}'.")
            else:
                col.delete(where={"langcode": langcode})
                logger.info(f"🗑️  Ingest API: Deleted '{langcode}' entries from '{collection_name}'.")
        except Exception as e:
            err_msg = str(e).lower()
            if "does not exist" in err_msg or "not found" in err_msg:
                logger.info(f"ℹ️  Ingest API: Collection '{collection_name}' does not exist. Nothing to delete.")
            else:
                raise

        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Ingest reset failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/ingest/languages', methods=['GET'])
def ingest_languages() -> Union[Response, Tuple[Response, int]]:
    """
    Lists distinct language codes found in the glossary and TM collections.

    Returns:
        glossary_langs (list[str]): Language codes in the glossary collection.
        tm_langs (list[str]): Language codes in the TM collection.
        all_langs (list[str]): Union of both, sorted alphabetically.
    """
    try:
        client = get_chroma_client()
        existing_collections = [c.name for c in client.list_collections()]

        glossary_langs: set = set()
        tm_langs: set = set()

        for col_name, lang_set in [
            (Config.GLOSSARY_COLLECTION, glossary_langs),
            (Config.TM_COLLECTION, tm_langs),
        ]:
            if col_name not in existing_collections:
                continue
            try:
                col = client.get_collection(col_name)
                # Fetch all metadata to extract unique langcodes.
                # limit=0 doesn't work in ChromaDB, so we use a large limit.
                results = col.get(include=["metadatas"])
                for meta in results.get("metadatas", []):
                    lc = (meta or {}).get("langcode", "")
                    if lc:
                        lang_set.add(lc)
            except Exception as e:
                logger.warning(f"⚠️ Could not read languages from '{col_name}': {e}")

        all_langs = sorted(glossary_langs | tm_langs)
        return jsonify({
            "glossary_langs": sorted(glossary_langs),
            "tm_langs": sorted(tm_langs),
            "all_langs": all_langs,
        })
    except Exception as e:
        logger.error(f"❌ Ingest languages failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/ingest/check-ids', methods=['POST'])
def ingest_check_ids() -> Union[Response, Tuple[Response, int]]:
    """
    Checks which IDs already exist in a collection (for incremental loading).

    Body:
        collection (str): Collection name.
        ids (list[str]): List of document IDs to check.

    Returns:
        existing_ids (list[str]): IDs that already exist in the collection.
    """
    try:
        data = request.json or {}
        collection_name = data.get("collection", "")
        ids = data.get("ids", [])

        if not collection_name or not ids:
            return jsonify({"error": "'collection' and 'ids' are required"}), 400

        client = get_chroma_client()

        try:
            col = client.get_or_create_collection(
                name=collection_name,
                embedding_function=get_embedding_function(),
                metadata={"hnsw:space": "cosine", "embedding_model": Config.EMBEDDING_MODEL_NAME}
            )
            # get_or_create_collection silently ignores metadata when the collection
            # already exists.  Force-update the embedding_model field so a collection
            # that survived a partial switch always reflects the current model.
            # NOTE: do NOT include hnsw:space here — ChromaDB forbids changing the
            # distance function after collection creation and will raise a ValueError.
            col.modify(metadata={"embedding_model": Config.EMBEDDING_MODEL_NAME})
            existing = col.get(ids=ids, include=[])
            return jsonify({"existing_ids": existing["ids"]})
        except Exception as e:
            logger.warning(f"⚠️ Failed to check IDs in '{collection_name}': {e}")
            return jsonify({"existing_ids": []})

    except Exception as e:
        logger.error(f"❌ Ingest check-ids failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/ingest/add', methods=['POST'])
def ingest_add() -> Union[Response, Tuple[Response, int]]:
    """
    Embeds and stores documents in a ChromaDB collection.
    The rag-proxy handles embedding so the caller doesn't need sentence-transformers.

    Body:
        collection (str): Collection name.
        ids (list[str]): Document IDs.
        documents (list[str]): Document texts to embed.
        metadatas (list[dict]): Metadata for each document.

    Returns:
        added (int): Number of documents added.
    """
    try:
        data = request.json or {}
        collection_name = data.get("collection", "")
        ids = data.get("ids", [])
        documents = data.get("documents", [])
        metadatas = data.get("metadatas", [])

        if not collection_name or not ids or not documents:
            return jsonify({"error": "'collection', 'ids', and 'documents' are required"}), 400

        if len(ids) != len(documents):
            return jsonify({"error": "ids and documents must have the same length"}), 400

        client = get_chroma_client()
        col = client.get_or_create_collection(
            name=collection_name,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine", "embedding_model": Config.EMBEDDING_MODEL_NAME}
        )
        # Force-update the embedding_model field in case the collection pre-dates
        # this model switch.  Do NOT include hnsw:space — ChromaDB forbids changing
        # the distance function after creation and will raise a ValueError.
        col.modify(metadata={"embedding_model": Config.EMBEDDING_MODEL_NAME})

        kwargs = {"ids": ids, "documents": documents}
        if metadatas:
            kwargs["metadatas"] = metadatas

        col.add(**kwargs)
        logger.info(f"📥 Ingest API: Added {len(ids)} documents to '{collection_name}'.")

        return jsonify({"added": len(ids)})
    except Exception as e:
        logger.error(f"❌ Ingest add failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check() -> Tuple[Response, int]:
    """
    Healthz endpoint for Docker and Load Balancers.
    Checks connectivity to Vector Database.
    """
    try:
        client = get_chroma_client()
        client.heartbeat()
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}", exc_info=True)
        return jsonify({"status": "error", "database": "disconnected", "details": str(e)}), 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
