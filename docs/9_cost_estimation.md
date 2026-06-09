# Cost Estimation

Before a live translation run, the system shows a cost estimate without making any API calls.

## How it works

**Input tokens** are estimated from the source `.po` files:

```
input_tokens = (total source chars + 30 chars/slot for JSON wrapping) ÷ 4
             + (batches × overhead_per_batch)
```

The `4 chars/token` heuristic is a deliberate overestimate (real BPE tokenisers average ~3.5–4.5 for English), making the estimate lean conservative.

**Overhead per batch** covers the system prompt, user-message boilerplate, and optional RAG context:

| Component | Tokens | Condition |
|---|---|---|
| System prompt | 375 | always |
| User-message boilerplate | 100 | always |
| RAG context (glossary + TM hits) | 200 | With RAG only |

The RAG overhead figure (200 tokens ≈ 800 characters) is an average estimate based on a typical glossary hit plus one TM match per batch. Actual RAG context varies with glossary size and TM coverage, so real costs with RAG will differ from this estimate.

**Output tokens** are unknown before translation, so a range is shown:

```
cost_low  = input_tokens × prompt_rate  +  input_tokens × 1.0 × completion_rate
cost_high = input_tokens × prompt_rate  +  input_tokens × 2.0 × completion_rate
```

The 1× lower bound assumes translations are roughly the same length as the source; the 2× upper bound accounts for verbose target languages and JSON array wrapping.

Rates are read from the `pricing` block in `config/models.yaml`. If a model has no pricing entry, the estimate shows `N/A` — add a `pricing` block to enable it:

```yaml
- id: my-model
  name: My Model
  provider: openai
  pricing:
    prompt_per_1k_tokens: 0.002
    completion_per_1k_tokens: 0.008
```
