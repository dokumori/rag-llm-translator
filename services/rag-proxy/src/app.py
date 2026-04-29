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

# --- Clients (Lazy & Cached) ---
_upstream_client = None


def get_upstream_client() -> OpenAI:
    """Returns a cached instance of the OpenAI client."""
    global _upstream_client
    if _upstream_client is None:
        _upstream_client = OpenAI(
            api_key=Config.LLM_API_TOKEN,
            base_url=Config.LLM_BASE_URL
        )
    return _upstream_client


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

@functools.lru_cache(maxsize=1)
def get_models_config() -> List[Dict[str, Any]]:
    """
    Retrieves model configurations from the shared JSON file, with custom override support.
    Uses load_models_config() to merge config/models/models.json with config/models/custom/models.json.
    """
    return load_models_config()


# Log configuration at startup
Config.log_config()

# --- Helper Functions ---

def parse_input_payload(source_text: str) -> List[Dict[str, str]]:
    """
    Extracts the content to be translated using the 'Sliding Window' JSON parsing logic.
    Returns a cleaned list of dictionary objects with 'text' and 'context'.
    """
    query_payload: List[Any] = []
    
    # Extract global context from gpt-po-translator prompt prefix if present
    global_context = ""
    context_match = re.search(r"CONTEXT:\s*(.*?)\nIMPORTANT: Choose the translation", source_text)
    if context_match:
        global_context = context_match.group(1).strip()

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

    # Fallback: Treat as single item if no JSON list was identified
    if not query_payload:
        query_payload = [source_text.strip()]

    # Clean the content by removing the "Text to translate:\n" prefix if present
    delimiter = "Text to translate:\n"
    cleaned_payload: List[Dict[str, str]] = []
    
    for item in query_payload:
        text = ""
        context = ""
        
        if isinstance(item, dict):
            # Extract text and developer-provided context (msgctxt) from gpt-po-translator 2.0.4+
            text = item.get("text", "") or item.get("string", "") or ""
            raw_context = item.get("context", None)
            context = raw_context if raw_context is not None else global_context
        elif isinstance(item, str):
            text = item
            context = global_context
        else:
            text = str(item)
            context = global_context
            
        if delimiter in text:
            text = text.split(delimiter)[-1]
            
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




def perform_rag_lookup(query_payload: List[Dict[str, str]], target_lang: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    """
    Queries ChromaDB, applies Guardrail logic (Glossary/TM), and returns
    the XML formatted context string and the list of match logs.
    
    When target_lang is provided, queries are filtered by langcode metadata
    so only context for the correct target language is retrieved.
    """
    rag_content = ""
    matches_log: List[Dict[str, Any]] = []
    found_glossary: set = set()
    found_tm: set = set()

    TM_THRESHOLD = Config.TM_THRESHOLD
    GLOSSARY_THRESHOLD = Config.GLOSSARY_THRESHOLD
    RAG_STRICT_DISTANCE_THRESHOLD = Config.RAG_STRICT_DISTANCE_THRESHOLD
    GLOSSARY_COLLECTION = Config.GLOSSARY_COLLECTION
    TM_COLLECTION = Config.TM_COLLECTION

    try:
        client = get_chroma_client()
        existing_collections = [c.name for c in client.list_collections()]

        # Prepare query texts and strip whitespace
        formatted_query = []
        for item in query_payload:
            text = item.get("text", "").strip()
            context = item.get("context", "").strip()
            # If context is available, append it to the query for better semantic retrieval
            if context:
                formatted_query.append(f"{text} context: {context}")
            else:
                formatted_query.append(text)

        # Build language filter for ChromaDB metadata queries
        lang_filter = {"langcode": target_lang} if target_lang else None

        def _query_with_context_fallback(collection, query_texts, lang_filter, batch_context, context_meta_key):
            """
            Runs a ChromaDB query respecting context isolation.

            Strategy:
              1. If batch_context is present, query with
                 (langcode == target_lang AND <context_meta_key> == batch_context).
                 If that returns no documents, fall back to lang-only.
              2. If batch_context is ABSENT (empty), query with
                 (langcode == target_lang AND <context_meta_key> == "").
                 This prevents context-specific entries from bleeding into
                 no-context strings (e.g. 'Italian' without msgctxt should
                 NOT match a glossary entry tagged with a specific msgctxt).
              3. If no lang_filter, query without any metadata filter.

            Returns (result, context_was_used: bool).
            """
            base_kwargs = {"query_texts": query_texts, "n_results": 1}

            if lang_filter and batch_context:
                # --- Pass 1: context-specific query ---
                ctx_kwargs = {**base_kwargs, "where": {"$and": [{"langcode": target_lang}, {context_meta_key: batch_context}]}}
                try:
                    ctx_res = collection.query(**ctx_kwargs)
                    has_any = any(doc_list for doc_list in ctx_res.get("documents", []))
                    if has_any:
                        logger.info(f"   🎯 Context-filtered query succeeded (context_key='{context_meta_key}', context='{batch_context}')")
                        return ctx_res, True
                    else:
                        logger.info(f"   ⚠️ Context-filtered query returned no results; falling back to lang-only filter (context='{batch_context}')")
                except Exception as ctx_err:
                    logger.warning(f"   ⚠️ Context-filtered query failed ({ctx_err}); falling back to lang-only filter")

                # --- Fallback: context-free entries only ---
                # Using lang-only would risk returning entries for a *different* msgctxt.
                # Instead, restrict the fallback to entries that have no context at all,
                # which are safe to apply regardless of the caller's context.
                ctx_free_kwargs = {
                    **base_kwargs,
                    "where": {"$and": [{"langcode": target_lang}, {context_meta_key: ""}]}
                }
                try:
                    ctx_free_res = collection.query(**ctx_free_kwargs)
                    has_any = any(doc_list for doc_list in ctx_free_res.get("documents", []))
                    if has_any:
                        logger.info(f"   ↩️  Context-free fallback succeeded (no '{batch_context}' entries found).")
                        return ctx_free_res, False
                    else:
                        logger.info(f"   ⚠️ Context-free fallback also returned no results; using lang-only filter.")
                except Exception as fb_err:
                    logger.warning(f"   ⚠️ Context-free fallback failed ({fb_err}); using lang-only filter.")

                # Last resort: full lang-only filter (catches pre-isolation ingested entries)
                return collection.query(**{**base_kwargs, "where": lang_filter}), False

            elif lang_filter:
                # No batch_context: restrict to context-free entries only
                # so context-specific glossary entries don't bleed into no-context strings.
                no_ctx_kwargs = {**base_kwargs, "where": {"$and": [{"langcode": target_lang}, {context_meta_key: ""}]}}
                try:
                    no_ctx_res = collection.query(**no_ctx_kwargs)
                    has_any = any(doc_list for doc_list in no_ctx_res.get("documents", []))
                    if has_any:
                        return no_ctx_res, False
                    else:
                        logger.info(f"   ⚠️ No context-free entries found; falling back to lang-only filter")
                except Exception as no_ctx_err:
                    logger.warning(f"   ⚠️ Context-free query failed ({no_ctx_err}); falling back to lang-only filter")

                # Fallback: lang-only (catches entries ingested before context isolation was enforced)
                return collection.query(**{**base_kwargs, "where": lang_filter}), False
            else:
                return collection.query(**base_kwargs), False

        # Process Glossary
        if GLOSSARY_COLLECTION in existing_collections:
            gloss_col = client.get_collection(
                GLOSSARY_COLLECTION,
                embedding_function=get_embedding_function()
            )
            
            # Group items by context to optimize queries
            gloss_groups = {}
            for i, item in enumerate(query_payload):
                ctx = item.get("context", "").strip()
                if ctx not in gloss_groups:
                    gloss_groups[ctx] = []
                gloss_groups[ctx].append((i, formatted_query[i], item.get("text", "")))

            for item_context, group_items in gloss_groups.items():
                group_indices = [g[0] for g in group_items]
                group_formatted_texts = [g[1] for g in group_items]
                group_original_texts = [g[2] for g in group_items]

                gloss_res, gloss_ctx_used = _query_with_context_fallback(
                    gloss_col, group_formatted_texts, lang_filter, item_context, "context"
                )
                if gloss_res['documents']:
                    for j, doc_list in enumerate(gloss_res['documents']):
                        if doc_list:
                            item_index = group_indices[j]  # Original batch index for log correlation
                            query_text = group_original_texts[j]
                            dist = gloss_res['distances'][j][0]
                            src = doc_list[0]
                            tgt = gloss_res['metadatas'][j][0].get('target', '')

                            # --- GUARDRAIL (GLOSSARY) ---
                            is_semantic_match = dist < GLOSSARY_THRESHOLD
                            has_shared_words = has_shared_stems(query_text, src)

                            # Reject if no shared words unless distance is extremely low (synonym exception)
                            if not has_shared_words and dist > RAG_STRICT_DISTANCE_THRESHOLD:
                                is_accepted = False
                                logger.info(
                                    f"   🛡️ Glossary Guardrail Rejection: '{query_text}' vs '{src}' (Dist: {dist:.4f}, No shared words)")
                            else:
                                is_accepted = is_semantic_match

                            matches_log.append({
                                "type": "glossary", "item_index": item_index, "context": item_context if gloss_ctx_used else "",
                                "untranslated_string": query_text, "rag_context": src, "tgt": tgt,
                                "dist": dist, "accepted": is_accepted, "no_shared_words": not has_shared_words
                            })

                            if is_accepted:
                                found_glossary.add(f"- '{src}' -> '{tgt}'")

        # Process Translation Memory (TM)
        if TM_COLLECTION in existing_collections:
            tm_col = client.get_collection(
                TM_COLLECTION,
                embedding_function=get_embedding_function()
            )
            
            # Group items by context to optimize queries
            tm_groups = {}
            for i, item in enumerate(query_payload):
                ctx = item.get("context", "").strip()
                if ctx not in tm_groups:
                    tm_groups[ctx] = []
                tm_groups[ctx].append((i, formatted_query[i], item.get("text", "")))

            for item_context, group_items in tm_groups.items():
                group_indices = [g[0] for g in group_items]
                group_formatted_texts = [g[1] for g in group_items]
                group_original_texts = [g[2] for g in group_items]

                tm_res, tm_ctx_used = _query_with_context_fallback(
                    tm_col, group_formatted_texts, lang_filter, item_context, "msgctxt"
                )
                if tm_res['documents']:
                    for j, doc_list in enumerate(tm_res['documents']):
                        if doc_list:
                            item_index = group_indices[j]  # Original batch index for log correlation
                            query_text = group_original_texts[j]
                            dist = tm_res['distances'][j][0]
                            src = doc_list[0]
                            tgt = tm_res['metadatas'][j][0].get('target', '')

                            # --- GUARDRAIL (TM) ---
                            is_semantic_match = dist < TM_THRESHOLD
                            has_shared_words = has_shared_stems(query_text, src)

                            if not has_shared_words and dist > RAG_STRICT_DISTANCE_THRESHOLD:
                                is_accepted = False
                                logger.info(
                                    f"   🛡️ TM Guardrail Rejection: '{query_text}' vs '{src}' (Dist: {dist:.4f}, No shared words)")
                            else:
                                is_accepted = is_semantic_match

                            matches_log.append({
                                "type": "tm", "item_index": item_index, "context": item_context if tm_ctx_used else "",
                                "untranslated_string": query_text, "rag_context": src, "tgt": tgt,
                                "dist": dist, "accepted": is_accepted, "no_shared_words": not has_shared_words
                            })

                            if is_accepted:
                                found_tm.add(f"Source: {src}\nTarget: {tgt}")



    except Exception as e:
        logger.error(f"⚠️ RAG Lookup skipped: {e}", exc_info=True)

    if found_glossary:
        rag_content += "\n<glossary_matches>\n" + \
            "\n".join(found_glossary) + "\n</glossary_matches>\n"
    if found_tm:
        rag_content += "\n<tm_matches>\n" + \
            "\n".join(found_tm) + "\n</tm_matches>\n"

    return rag_content, matches_log


def construct_system_prompt(original_system_data: Union[str, List[Dict[str, str]]], rag_content: str, target_lang: str) -> str:
    """Combines instructions, RAG context, and original system message."""
    expert_instructions = get_system_prompt_from_md(target_lang)

    original_system = original_system_data
    if isinstance(original_system, list):
        original_system = " ".join([s.get('text', '')
                                   for s in original_system if 'text' in s])

    return f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

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
        requested_model = (data.get('model') or "claude-opus-4-5-20251101").strip()

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
            data.get('system', ""), rag_content, target_lang)

        # --- 4. STRUCTURED LOGGING ---
        log_entry["system_prompt_length"] = len(final_system_content)
        logger.info(json.dumps(log_entry, ensure_ascii=False))

        # --- 4a. PREPARE PAYLOAD ---
        # Strip only the "CONTEXT: ...\nIMPORTANT: ..." prefix block injected by
        # gpt-po-translator. We use a targeted regex so we don't accidentally remove
        # the library's own JSON format instructions that follow the prefix.
        # (The old find('[') approach was too aggressive and stripped those instructions too.)
        cleaned_source_text = re.sub(
            r'^CONTEXT:.*?(?=\nProvide only|\nTexts to translate:|\[)',
            '',
            source_text,
            flags=re.DOTALL
        ).lstrip()

        def _clean_user_message(msg: Dict[str, Any]) -> Dict[str, Any]:
            """Replace raw content with the prefix-stripped version for the last user message."""
            if msg.get('role') == 'user' and msg.get('content') == source_text:
                return {**msg, 'content': cleaned_source_text}
            return msg

        new_messages = [{"role": "system", "content": final_system_content}]
        new_messages += [_clean_user_message(m) for m in messages if m.get('role') != 'system']

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
            response = get_upstream_client().chat.completions.create(
                model=requested_model,
                messages=new_messages,
                temperature=0,
                max_tokens=data.get('max_tokens', 1000)
            )
            
            # --- API ERROR CHECKS ---
            for choice in response.choices:
                if choice.finish_reason in ["safety", "content_filter"]:
                    logger.warning(f"🚨 GUARDRAIL BLOCKED TRANSLATION! Finish Reason: {choice.finish_reason}")
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
