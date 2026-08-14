# Running Benchmarks and Experiments

OxCidation uses the same runner for the prompt-selection benchmark and the
main experiment. The difference is the selected prompts:

- **Prompt-selection benchmark:** omit `--prompt-id` to run every prompt in
  `prompts/benchmark/` for every selected program.
- **Main experiment:** pass one `--prompt-id` to run only the prompt chosen by
  the benchmark.

Every command writes an isolated directory under `outputs/<experiment-id>/`.
At completion it prints the paths to `results.csv` and `review_workbook.xlsx`.

## Dataset Root

For an integrated Judge run, place the accepted-C subset, mapping output, and
AOJ suites under one directory:

```text
<dataset-root>/
  data/
  metadata/
  manifests/aoj_problem_mapping/benchmark_population.csv
  judge_tests/
```

The bundled population manifest contains one accepted C submission per mapped
problem. `judge_tests/` contains the mapped AOJ input/output directories. This
layout lets the runner derive every dataset path from `--dataset-root`.

The preparation commands are documented in the repository README. When
creating a new package, write the mapping output to
`manifests/aoj_problem_mapping/` and the AOJ suite output to `judge_tests/`.

## Run a Prompt-Selection Benchmark

Select the model through `OXCIDATION_CONFIG_FILE`, export its API key, and omit
`--prompt-id` so all benchmark prompts run. The example below is a small,
five-program integration check with Gemini 3.5 Flash-Lite.

```bash
GEMINI_API_KEY="..." \
OXCIDATION_CONFIG_FILE=config/gemini-3.5-flash-lite.yaml \
./.venv/bin/python src/benchmark.py \
  --experiment-id gemini-3.5-flash-lite-benchmark-smoke-01 \
  --dataset-root /path/to/OxCidation_dataset \
  --sample-size 5 \
  --seed 42
```

The run selects five Judge-eligible programs after filtering, prepares one
frozen visible-test suite per program, and evaluates every prompt in
`prompts/benchmark/`. Its output contains one result row per `program x prompt`
combination.

## Run the Main Experiment

After choosing and freezing a prompt, run the same command with one
`--prompt-id`. Replace the placeholder with the selected prompt's filename
without `.txt`.

```bash
GEMINI_API_KEY="..." \
OXCIDATION_CONFIG_FILE=config/gemini-3.5-flash-lite.yaml \
./.venv/bin/python src/benchmark.py \
  --experiment-id gemini-3.5-flash-lite-main-01 \
  --dataset-root /path/to/OxCidation_dataset \
  --prompt-id <frozen-prompt-id> \
  --sample-size 100 \
  --seed 42
```

This runs one model and one prompt for each selected program. It preserves the
initial and final translations, visible-test evidence, and initial/final Judge
observations.

## Resume an Interrupted Run

Run the same command again with `--resume`. Do not change the experiment ID,
dataset contents, prompt files, model configuration, seed, or selected prompt.
The runner verifies the original manifest and completed artifacts before it
continues.

```bash
GEMINI_API_KEY="..." \
OXCIDATION_CONFIG_FILE=config/gemini-3.5-flash-lite.yaml \
./.venv/bin/python src/benchmark.py \
  --experiment-id gemini-3.5-flash-lite-main-01 \
  --dataset-root /path/to/OxCidation_dataset \
  --prompt-id <frozen-prompt-id> \
  --sample-size 100 \
  --seed 42 \
  --resume
```

## Advanced Paths

`--input-dir`, `--source-manifest`, `--metadata-root`, and
`--judge-tests-root` remain available for an unusual directory layout or a
translation-only run. Do not combine different mappings or Judge suites inside
one experiment: the manifest records the selected source, prompt, model, and
Judge profile so that resumed and reported results remain reproducible.
