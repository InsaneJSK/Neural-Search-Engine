# Prototype validation — 21 September 2026

Verified locally with n8n 2.39.8, Node 24.21.0, MCP Python SDK 1.30.0,
Ollama `qwen3:4b`, Tavily keyless search, and both saved BERT checkpoints on CPU.

- **36 automated tests passed**, including the existing model, provider, and
  evaluation tests plus HTTP/MCP lifecycle, validation, errors, and concurrency.
- The standalone MCP client initialized, discovered `neural_search`, and returned
  five ranked sources from a live search.
- All three workflow JSON files imported and executed successfully in n8n's
  actual execution engine, using its HTTP Request and native MCP Client nodes.

| Workflow | Candidates | Returned sources | Observed execution time |
| --- | ---: | ---: | ---: |
| HTTP evidence | 20 | 5 | 13.7 seconds |
| MCP evidence | 20 | 5 | 8.4 seconds |
| HTTP evidence + Qwen answer | 20 | 5 | 67.3 seconds |

These are individual functional runs, not comparative benchmarks. n8n process
startup and initial model loading are outside these workflow execution times.
The final answer was 113 words with individually bracketed citations whose IDs
all existed in the returned source set. The output preserves the full evidence.

An initial Qwen run exhausted its output budget. The first implementation checked
truncation and citation IDs inside a Set-node expression. This Ollama/model pair
also emitted a reasoning preamble ending in `</think>` despite `think: false`;
that implementation extracted the text after the marker. It was superseded by
the structured-output repair below.

**Factual support was not validated.** The sample answer repeated an all-pairs
sentence-comparison cost without clearly stating that assumption. That cost does
not describe the NSE pipeline's single-query reranking of ten candidates.
Citation checks cannot detect this contextual error. Successful workflow
execution is not evidence of answer correctness or improved retrieval quality.

Local diagnostic artifacts are saved under `.cache/nse/`:
`prototype-validation.json`, `prototype-answer.json`, `n8n-search-execution.log`,
`n8n-mcp-execution.log`, and `n8n-answer-execution.log`. The full retrieval-quality
results are separately preserved in the
[30-query evaluation report](../evals/results/2026-09-21-tavily.md).

## Answer-workflow regression and repair

A subsequent user execution exhausted the 1,536-token output budget on a draft.
The Set-node expression threw during validation, and n8n displayed the misleading
error `Cannot convert undefined or null to object` instead of the intended message.

The repaired workflow has six nodes. A **Prepare answer request** JavaScript Code
node validates the evidence budget and builds an Ollama request with a JSON
schema requiring an `answer` string. **Answer and evidence** is now a Code node
that parses and validates the finished response, rejecting truncation, invalid
JSON, reasoning tags, excessive length, and missing or unknown citations.
Errors are raised directly from the Code node, not from an expression returning
an undefined value. The source evidence is retained unchanged.

The repair was executed through n8n with the user's question:
“What is semantic search, and how does it differ from keyword search?”
It completed successfully at `2026-09-21T05:24:38.670Z`, with a **98-token**
Ollama response and `done_reason: stop`. Workflow duration was **12.7 seconds**
in this single functional run; this is not a latency benchmark. All cited IDs
existed in the same execution's evidence. Factual correctness remains ungraded.

**Seven JavaScript regression tests passed**, running the actual Code-node
programs from the workflow JSON. They cover the schema request, evidence-size
guard, the reported truncation failure, malformed/incomplete responses, citation
validation, evidence preservation, and empty evidence. Run them with
`node --test tests/workflow-answer.test.cjs`.

The previous imported workflow was backed up to
`.cache/nse/answer-workflow-before-fix.json`; the successful repaired run and its
output are in `.cache/nse/answer-fix-execution.log` and
`.cache/nse/answer-fix-result.json`. The installed workflow was updated in place;
refresh an already-open editor and execute the complete workflow to avoid using
the previous truncated node output.
