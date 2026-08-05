# Benchmark Prompt Provenance

These templates adapt initial-translation prompts cataloged in
`Translation Task Prompts in LLM Research Papers.xlsx`. The benchmark injects
the selected C source at `{c_code}` and requests structured Rust output through
the model provider.

## Included prompts

| Prompt ID | Source paper | Paper approach | Adaptation |
| --- | --- | --- | --- |
| `direct-v1` | Project control; not derived from a paper | Direct behavior-preserving translation | Existing OxCidation baseline retained without adaptation. |
| `trace-zero-shot-v1` | *TRACE: Evaluating Execution Efficiency of LLM-Based Code Translation* | Zero-shot translation | Replaced generic source/target placeholders with C/Rust and removed Markdown and `<\|END\|>` wrappers. |
| `trace-performance-v1` | *TRACE: Evaluating Execution Efficiency of LLM-Based Code Translation* | Performance-aware zero-shot translation | Applied the same interface changes while retaining the efficiency and best-practices instruction. |
| `realworld-safe-constraints-v1` | *Towards Translating Real-World Code with LLMs: A Study of Translating to Rust* | Zero-shot translation with specific constraints | Specialized C/Go to C and retained only constraints explicitly present in the spreadsheet excerpt. |
| `rustmap-instruction-v1` | *RustMap: Towards Project-Scale C-to-Rust Migration via Program Analysis and LLM* | Instruction-based C-to-Rust prompting | Removed the interactive “ask me first” behavior because benchmark programs are complete and execution is unattended. Retained its idiomatic-Rust and implementation-detail guidance. |
| `safetrans-safe-v1` | *SafeTrans: LLM-assisted Transpilation from C to Rust* | Zero-shot base transpilation | Removed the Markdown wrapper and retained safe Rust, complete compilation, and code-only requirements. |

## Excluded prompts

- TRACE performance-aware few-shot requires a fixed, independently selected
  set of efficient translation examples. Adding arbitrary examples would change
  the paper's approach and introduce another experimental variable.
- TRACE self-refine requires an existing reference translation plus test,
  execution-time, and memory feedback. It is a later-stage refinement prompt,
  not an initial translation prompt.
- BaseRepair, CAPR, SafeTrans compilation repair, SafeTrans dynamic repair,
  and SafeTrans few-shot repair operate on an existing faulty Rust translation.
  They are not candidates for the initial translation-prompt benchmark.
- RustMap semantic repair requires matched C/Rust runtime before-and-after
  states, which the current pipeline does not collect.

The source spreadsheet contains abbreviated templates with ellipses for some
papers. No missing constraints or examples were invented.
