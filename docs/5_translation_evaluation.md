# Translation Evaluation (LLM-as-a-Judge)

## 1. Overview

The translation evaluation feature operates as an automated 'blind test', which uses an LLM as an independent judge to compare two separate translations: one created with RAG context, and one created without it. This process provides an objective way to measure accuracy, contextual suitability, and the overall improvement that the RAG system delivers.

## 2. How to Evaluate Translations

1. **Produce translation files**  
   Run the translation script twice to generate two sets of `.po` translation files for the same source text: one translation using the RAG context, and one translation without using it.
   
2. **Store the translated .po files in the correct directories**  
   Place exactly one `.po` file in each of the following directories:
   - RAG translations: `data/translations/eval/with_rag/`
   - Non-RAG translations: `data/translations/eval/without_rag/`

3. **Run the evaluation script**  
   From the main project folder, run the following shell command:
   ```bash
   ./bin/eval_quality.sh
   ```

4. **Choose the options**  
   The script will prompt you to:
   - Select the LLM model to act as the judge (or choose a 'dry run' model for testing).
   - Select the evaluation sample limit. You can choose a custom limit, evaluate all strings, or use the recommended statistical sample.
     - This recommended sample size is automatically calculated using Cochran's formula to provide a 95% confidence level with a 5% margin of error, ensuring statistically reliable results without the need to evaluate every single string.

5. **Find the results**  
   Once the process finishes, you will find the generated `.csv` and `.txt` result files in this directory:
   - `data/translations/eval/`

## 3. How translations are judged

The evaluation system processes the translation files step by step, scoring each string individually. Here is a clear breakdown of the evaluation process:

1. **Extracting and mapping**  
   The script reads the generated translation files to collect the translated strings. It uses the original source text as unique keys to correctly match the RAG translation with the non-RAG translation for an accurate comparison.

2. **Randomising the order**  
   To avoid bias, the paired translations for each string are placed in an array and their positions are randomised. This creates a genuine blind test, ensuring the LLM judge cannot guess which translation used RAG context based on its position.

3. **Retrieving fresh context**  
   The system runs a fresh RAG query to supply the judge with current context. There is no need to use historical logs from the original translation process; running a new query with identical text produces exactly the same context.

4. **Evaluating the translations**  
   Before evaluating, the system applies a guardrail to check the retrieved context. If the context is irrelevant or if the two translations are virtually identical, the string is ignored to save time and API costs.
   
   For the valid strings, the system sends the judge LLM the randomised pair of translations, the fresh context, the original text, and an evaluation prompt. The judge then decides which translation is more accurate and better suits the context.

5. **Saving the results**  
   The final evaluations are collected and saved in two formats:
   - **Detailed Results (`.csv`)**: A comprehensive record showing the results for every string, including individual scores, the chosen translation, and the judge's reasoning.
   - **Summary Report (`.txt`)**: A clear, brief summary showing the overall performance and comparing the success rates of both translation methods.
