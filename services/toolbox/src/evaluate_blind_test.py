"""
Evaluates translation quality using an LLM-as-a-Judge blind test.

For each source string, the script retrieves relevant TM/glossary
context from a RAG database. It then compares translations from two
files (with RAG and without RAG) to determine which file contains
superior translations, focusing specifically on adherence to the
retrieved context.
"""

import os
import sys
import glob
import json
import random
import csv
import logging
import argparse
from typing import List, Dict, Any, Tuple
import datetime
from openai import OpenAI
from core.config import load_models_config

# Attempt to import tools for getting context from db
try:
    import polib
except ImportError:
    print("❌ Error: polib is required. Run: pip install polib")
    sys.exit(1)

# In the toolbox container, /app/services/rag-proxy/src is in PYTHONPATH
try:
    from app import perform_rag_lookup
except ImportError:
    # Fallback if run from host
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "rag-proxy", "src")))
    from app import perform_rag_lookup

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_po_translations(directory: str) -> Tuple[Dict[str, str], List[str]]:
    """
    Loads all translated strings from .po files found within the specified 
    directory (typically subdirectories within data/translations/eval/).
    """
    translations = {}
    found_files = []
    po_files = glob.glob(os.path.join(directory, "**/*.po"), recursive=True)
    for file_path in po_files:
        try:
            po = polib.pofile(file_path)
            found_files.append(file_path)
            for entry in po:
                if entry.msgid and entry.msgstr:
                    # Context-Aware Key: (msgid, msgctxt)
                    key = (entry.msgid, entry.msgctxt or "")
                    translations[key] = entry.msgstr
        except Exception as e:
            logger.error(f"Failed to load {file_path}: {e}")
    return translations, found_files

def pair_translations(with_rag_dir: str, without_rag_dir: str) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    """
    Pairs translations from the two sets of translated files by matching their 
    msgid. Ensures that only strings found in both the with-RAG and 
    without-RAG folders are included for the comparison.
    """
    with_rag_data, with_rag_files = load_po_translations(with_rag_dir)
    without_rag_data, without_rag_files = load_po_translations(without_rag_dir)
    
    paired_data = []
    
    for (msgid, msgctxt), with_rag_str in with_rag_data.items():
        if (msgid, msgctxt) in without_rag_data:
            paired_data.append({
                "source": msgid,
                "context": msgctxt,
                "with_rag": with_rag_str,
                "without_rag": without_rag_data[(msgid, msgctxt)]
            })
            
    # Return the mapped translation pairs for LLM evaluation, along with the 
    # original file paths used to generate the final summary report.
    return paired_data, with_rag_files, without_rag_files

def get_judge_prompt_template() -> str:
    """
    Reads the 'judge_evaluation.md' template from the directory defined 
    by the PROMPTS_DIR environment variable. This template provides 
    instructions for the LLM-as-a-Judge.
    """
    prompt_path = os.environ.get("PROMPTS_DIR", "/app/config/prompts")
    prompt_file = os.path.join(prompt_path, "judge_evaluation.md")
    
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"Failed to load judge prompt template from {prompt_file}: {e}")
        sys.exit(1)

def format_file_info(file_paths: List[str]) -> str:
    """
    Formats a list of file paths into a human-readable string showing
    each filename and its immediate parent directory.
    """
    if not file_paths:
        return "None"
    info = []
    for fp in file_paths:
        fname = os.path.basename(fp)
        dname = os.path.basename(os.path.dirname(fp))
        info.append(f"{fname} (in {dname}/)")
    return ", ".join(info)

def evaluate_translation(client: OpenAI, model: str, sample: Dict[str, str], prompt_template: str, dry_run: bool = False) -> Dict[str, Any]:
    """Calls the Judge LLM to evaluate the pair, or returns mock data on dry run."""
    source_text = sample["source"]
    source_context = sample.get("context", "")
    
    # 1. Re-Retrieve Context from ChromaDB
    try:
        # Use new context-aware dictionary payload format
        rag_context, _ = perform_rag_lookup([{"text": source_text, "context": source_context}])
        if not rag_context.strip():
            logger.info(f"⏭️ Skipping '{source_text[:30]}...' (No RAG context or Guardrail rejected)")
            return None
    except Exception as e:
        logger.warning(f"Could not retrieve RAG context for evaluation: {e}")
        return None
        
    # 2. Dry Run: return a mock result without making an API call
    if dry_run:
        winner = random.choice(["with_rag", "without_rag", "tie"])
        logger.info(f"   🔬 [DRY RUN] Skipping API call for '{source_text[:30]}...'. Mock winner: {winner.upper()}")
        return {
            "source": source_text,
            "rag_context": rag_context,
            "with_rag_translation": sample["with_rag"],
            "without_rag_translation": sample["without_rag"],
            "winner": winner,
            "with_rag_context": 3.0,
            "with_rag_fluency": 3.0,
            "with_rag_reason": "[DRY RUN] No API call made.",
            "without_rag_context": 3.0,
            "without_rag_fluency": 3.0,
            "without_rag_reason": "[DRY RUN] No API call made.",
        }

    # 3. Randomize A and B
    is_with_rag_a = random.choice([True, False])
    
    if is_with_rag_a:
        trans_a = sample["with_rag"]
        trans_b = sample["without_rag"]
    else:
        trans_a = sample["without_rag"]
        trans_b = sample["with_rag"]

    # 4. Format Prompt
    context_line = f"- Context (msgctxt): {source_context}\n" if source_context else ""
    system_prompt = prompt_template.replace(
        "{source_text}", source_text
    ).replace(
        "{source_context}", context_line
    ).replace(
        "{rag_context}", rag_context
    ).replace(
        "{translation_a}", trans_a
    ).replace(
        "{translation_b}", trans_b
    )

    # 5. Call Model
    logger.info(f"   🤖 Sending '{source_text[:30]}...' to Judge for evaluation...")
    
    # Write verbose prompt to Docker daemon ONLY
    try:
        with open("/proc/1/fd/1", "a", encoding="utf-8") as docker_log:
            docker_log.write(f"\n{'='*60}\n")
            docker_log.write(f"TIMESTAMP: {datetime.datetime.now().isoformat()}\n")
            docker_log.write(f"SOURCE   : {source_text}\n")
            docker_log.write(f"\n--- PROMPT SENT ---\n{system_prompt}\n")
            docker_log.write(f"{'-'*60}\n")
    except Exception:
        pass
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": system_prompt}],
            temperature=0,
            response_format={"type": "json_object"} if "gpt-" in model.lower() else None
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Write verbose response to Docker daemon ONLY
        try:
            with open("/proc/1/fd/1", "a", encoding="utf-8") as docker_log:
                docker_log.write(f"\n--- RESPONSE ---\n{response_text}\n")
                docker_log.write(f"{'='*60}\n")
        except Exception:
            pass
        
        # Strip markdown code fences if present, then strip surrounding whitespace
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        elif response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
            
        evaluation = json.loads(response_text)
        
        # 6. Resolve Winner
        better = str(evaluation.get("Better_Translation", "Tie")).strip().upper()
        if better == "A":
            winner = "with_rag" if is_with_rag_a else "without_rag"
        elif better == "B":
            winner = "without_rag" if is_with_rag_a else "with_rag"
        else:
            winner = "tie"
            
        logger.info(f"   ✅ Received Response. Winner: {winner.upper()}")
            
        # 7. Extract raw scores back to their translated files
        scores = {
            "with_rag_context": evaluation["Score_A"]["Context_Adherence"] if is_with_rag_a else evaluation["Score_B"]["Context_Adherence"],
            "with_rag_fluency": evaluation["Score_A"]["Accuracy_Fluency"] if is_with_rag_a else evaluation["Score_B"]["Accuracy_Fluency"],
            "with_rag_reason": evaluation["Score_A"]["Reason"] if is_with_rag_a else evaluation["Score_B"]["Reason"],
            
            "without_rag_context": evaluation["Score_B"]["Context_Adherence"] if is_with_rag_a else evaluation["Score_A"]["Context_Adherence"],
            "without_rag_fluency": evaluation["Score_B"]["Accuracy_Fluency"] if is_with_rag_a else evaluation["Score_A"]["Accuracy_Fluency"],
            "without_rag_reason": evaluation["Score_B"]["Reason"] if is_with_rag_a else evaluation["Score_A"]["Reason"],
        }
            
        return {
            "source": source_text,
            "rag_context": rag_context,
            "with_rag_translation": sample["with_rag"],
            "without_rag_translation": sample["without_rag"],
            "winner": winner,
            **scores
        }

    except Exception as e:
        logger.error(f"Evaluation failed for string: {source_text[:50]}... Error: {e}")
        return None

def run_evaluation_loop(client: OpenAI, model: str, paired_data: List[Dict[str, str]], limit: int, prompt_template: str, is_dry_run: bool) -> List[Dict[str, Any]]:
    """Runs the primary evaluation loop, calling the judge LLM for each sample."""
    target_evals = min(limit, len(paired_data)) if limit > 0 else len(paired_data)
    target_str = str(target_evals) if limit > 0 else "ALL"
    successful_evals = 0
    results = []

    # Main evaluation loop to send each translation pair to the LLM
    for idx, sample in enumerate(paired_data, 1):
        if limit > 0 and successful_evals >= target_evals:
            break
            
        logger.info(f"⏳ Evaluating [{successful_evals + 1}/{target_str}] (Attempt {idx}/{len(paired_data)})...")
        eval_result = evaluate_translation(client, model, sample, prompt_template, dry_run=is_dry_run)
        if eval_result:
            results.append(eval_result)
            successful_evals += 1
            
    return results

def calculate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes all aggregate and comparative metrics from the evaluation results."""
    if not results:
        logger.error("All evaluations failed.")
        sys.exit(1)
        
    # Win counts
    wins_with_rag = sum(1 for r in results if r["winner"] == "with_rag")
    wins_without_rag = sum(1 for r in results if r["winner"] == "without_rag")
    ties = sum(1 for r in results if r["winner"] == "tie")
    
    # Average context adherence
    avg_ctx_with = sum(float(r["with_rag_context"]) for r in results) / len(results)
    avg_ctx_without = sum(float(r["without_rag_context"]) for r in results) / len(results)
    
    # Average accuracy and fluency
    avg_fluency_with = sum(float(r["with_rag_fluency"]) for r in results) / len(results)
    avg_fluency_without = sum(float(r["without_rag_fluency"]) for r in results) / len(results)

    # Calculate comparative metrics
    wins_total_decisions = wins_with_rag + wins_without_rag
    # Win Ratio: How many times RAG won for every 1 time the baseline won
    win_ratio = wins_with_rag / wins_without_rag if wins_without_rag > 0 else float('inf')
    # Relative Win Rate: Percentage of non-tie cases won by RAG
    relative_win_rate = (wins_with_rag / wins_total_decisions * 100) if wins_total_decisions > 0 else 0
    # Net Improvement (Delta): Difference in win-rate across the entire sample (including ties)
    net_win_rate = (wins_with_rag - wins_without_rag) / len(results) * 100
    # Win Lead: percentage more 'Wins' than the baseline
    win_lead = ((wins_with_rag - wins_without_rag) / wins_without_rag * 100) if wins_without_rag > 0 else (100.0 if wins_with_rag > 0 else 0.0)

    # Raw Score Improvement (Context Adherence)
    # Measures the percentage increase in the average absolute score
    score_improvement = ((avg_ctx_with - avg_ctx_without) / avg_ctx_without * 100) if avg_ctx_without > 0 else 0

    # Contextual Error Reduction (Gap to perfection of 5.0)
    # Measures how much of the remaining 'error gap' was closed by RAG
    gap_without = 5.0 - avg_ctx_without
    gap_with = 5.0 - avg_ctx_with
    contextual_error_reduction = ((gap_without - gap_with) / gap_without * 100) if gap_without > 0 else 0

    # Sub-optimal Rate Reduction (Score < 4.0)
    # Reduction in translations that require manual polish or have minor context issues
    suboptimal_with = sum(1 for r in results if float(r["with_rag_context"]) < 4.0)
    suboptimal_without = sum(1 for r in results if float(r["without_rag_context"]) < 4.0)
    suboptimal_reduction = ((suboptimal_without - suboptimal_with) / suboptimal_without * 100) if suboptimal_without > 0 else 0

    return {
        "wins_with_rag": wins_with_rag,
        "wins_without_rag": wins_without_rag,
        "ties": ties,
        "avg_ctx_with": avg_ctx_with,
        "avg_ctx_without": avg_ctx_without,
        "avg_fluency_with": avg_fluency_with,
        "avg_fluency_without": avg_fluency_without,
        "win_ratio": win_ratio,
        "relative_win_rate": relative_win_rate,
        "net_win_rate": net_win_rate,
        "win_lead": win_lead,
        "score_improvement": score_improvement,
        "contextual_error_reduction": contextual_error_reduction,
        "suboptimal_reduction": suboptimal_reduction,
        "total_evaluated": len(results)
    }

def save_reports(output_dir: str, model_slug: str, results: List[Dict[str, Any]], metrics: Dict[str, Any], judge_name: str, model_id: str, with_rag_info: str, without_rag_info: str, is_dry_run: bool):
    """Generates the report, prints it, and saves it to CSV and text files."""
    now = datetime.datetime.now()
    completion_time = now.strftime("%Y-%m-%d %H:%M")

    report_content = [
        "=========================================",
        "🏆 EVALUATION RESULTS SUMMARY",
        f"Completed: {completion_time}",
        "=========================================",
        f"JUDGE MODEL ⚖️ : Dry Run Mode" if is_dry_run else f"JUDGE MODEL ⚖️ : {judge_name} ({model_id})",
        f"Total Evaluated: {metrics['total_evaluated']}",
        f"Wins (With RAG): {metrics['wins_with_rag']}",
        f"Wins (Without RAG): {metrics['wins_without_rag']}",
        f"Ties: {metrics['ties']}",
        "-----------------------------------------",
        "Files Compared:",
        f"  - With RAG: {with_rag_info}",
        f"  - Without RAG: {without_rag_info}",
        "-----------------------------------------",
        "Comparative Metrics (vs Non-RAG):",
        f"  - Win Ratio: {metrics['win_ratio']:.2f}x (RAG is {metrics['win_ratio']:.1f}x more likely to win)",
        f"  - Relative Win Rate: {metrics['relative_win_rate']:.1f}% (Preference in decided cases)",
        f"  - Win Lead: {metrics['win_lead']:+.1f}% (More 'Best' translations produced)",
        f"  - Contextual Error Reduction: {metrics['contextual_error_reduction']:.1f}% (Closing the gap to perfection)",
        f"  - Sub-optimal Rate Reduction: {metrics['suboptimal_reduction']:+.1f}% (Reduction in scores < 4.0)",
        f"  - Net Improvement (Delta): {metrics['net_win_rate']:+.1f}% (Total win-rate difference)",
        f"  - Score Improvement: {metrics['score_improvement']:+.1f}% (Average context score boost)",
        "-----------------------------------------",
        "Average Context Adherence Score (Max 5):",
        f"  - With RAG: {metrics['avg_ctx_with']:.2f}",
        f"  - Without RAG: {metrics['avg_ctx_without']:.2f}",
        "Average Accuracy & Fluency Score (Max 5):",
        f"  - With RAG: {metrics['avg_fluency_with']:.2f}",
        f"  - Without RAG: {metrics['avg_fluency_without']:.2f}",
        "=========================================",
        "For a detailed explanation of the evaluation methodology, see:",
        "docs/5_translation_evaluation.md"
    ]

    # Print Report to Console
    for line in report_content:
        logger.info(line)

    # Write Output Files
    timestamp = now.strftime("%Y-%m-%d_%H-%M")
    
    # Write to CSV
    output_report = os.path.join(output_dir, f"evaluation_report_{timestamp}_{model_slug}.csv")
    with open(output_report, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
        
    logger.info(f"📁 Detailed CSV report saved to {output_report}")

    # Write to Text Summary
    txt_report = os.path.join(output_dir, f"evaluation-result-{timestamp}_{model_slug}.txt")
    with open(txt_report, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_content))
        
    logger.info(f"📄 Summary text report saved to {txt_report}")

def main():
    parser = argparse.ArgumentParser(description="Evaluate translations with LLM-as-a-Judge")
    parser.add_argument("--model", required=True, help="LLM Model ID for the judge")
    parser.add_argument("--with-rag-dir", required=True, help="Directory containing with-RAG translations")
    parser.add_argument("--without-rag-dir", required=True, help="Directory containing without-RAG translations")
    parser.add_argument("--limit", type=int, default=0, help="Number of strings to evaluate (0 for all)")
    args = parser.parse_args()

    # Reset Base URL to hit provider directly if using standard OpenAI instead of local proxy
    if "OPENAI_BASE_URL" in os.environ:
        if "rag-proxy" in os.environ["OPENAI_BASE_URL"]:
            del os.environ["OPENAI_BASE_URL"]

    logger.info("🔍 Loading translation pairs...")
    paired_data, with_rag_files, without_rag_files = pair_translations(args.with_rag_dir, args.without_rag_dir)
    
    if not paired_data:
        logger.error("No valid translation pairs found matching source strings across both directories.")
        sys.exit(1)
        
    logger.info(f"📊 Found {len(paired_data)} overlapping translated strings.")

    if args.limit > 0:
        target_evals = min(args.limit, len(paired_data))
        logger.info(f"🎲 Randomly shuffling strings, looking to evaluate up to {target_evals} valid translations...")
        random.shuffle(paired_data)

    # Check if this model is marked as a dry run in the models config
    is_dry_run = False
    judge_name = args.model
    try:
        models_list = load_models_config()
        for m in models_list:
            if m["id"] == args.model:
                is_dry_run = bool(m.get("is_dry_run", False))
                judge_name = m.get("name", args.model)
                break
    except Exception as e:
        logger.warning(f"Could not read models config to check dry_run flag: {e}")

    if is_dry_run:
        logger.info("🔬 DRY RUN MODE: No API calls will be made. Mock results will be returned.")
        logger.info("🤖 Starting Evaluation in Dry Run Mode")
    else:
        logger.info(f"🤖 Starting Evaluation using model: {args.model}")

    prompt_template = get_judge_prompt_template()

    # Create a single shared OpenAI client for all evaluations
    client = OpenAI(
        # Pass 'dummy' to prevent it from crashing if the token is missing
        api_key=os.environ.get("LLM_API_TOKEN", "dummy"),
        base_url=os.environ.get("LLM_BASE_URL")
    )

    results = run_evaluation_loop(client, args.model, paired_data, args.limit, prompt_template, is_dry_run)
    metrics = calculate_metrics(results)
    
    with_rag_info = format_file_info(with_rag_files)
    without_rag_info = format_file_info(without_rag_files)
    
    output_dir = os.path.dirname(args.with_rag_dir.rstrip("/"))
    model_slug = "dry-run" if is_dry_run else judge_name.lower().replace(" ", "-")
    
    save_reports(output_dir, model_slug, results, metrics, judge_name, args.model, with_rag_info, without_rag_info, is_dry_run)

if __name__ == "__main__":
    main()
