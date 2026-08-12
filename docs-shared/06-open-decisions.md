# Open Decisions Before the Definitive Experiment

The software can already run a multi-prompt benchmark. The definitive study is
blocked mainly by decisions about what will be sampled, how prompts will be
compared, and which Judge evidence is valid. These choices must be made before
seeing the definitive results.

## 1. Choose the Model

**Current position:** Gemini profiles have been used for smoke tests, but the
benchmark model is not selected.

**Decision needed:** provider, exact model/version, generation parameters,
maximum output, request pacing, retry policy, and reasoning configuration when
applicable.

**Why first:** model behavior, cost, token accounting, and feasible sample size
depend on this choice.

## 2. Freeze the Candidate Prompts

**Current position:** one control and five paper-derived translation prompts are
implemented.

**Decision needed:** confirm the final candidate set and freeze every prompt
file. Completed runs identify prompts by ID, text, and hash, so later edits must
create new prompt versions.

## 3. Decide How a Prompt Wins

**Current position:** reports preserve initial translation quality, final
repaired quality, Judge outcomes, and repair dependence.

**Decision needed:** define the primary metric, tie-breakers, and smallest
difference worth detecting. Decide whether selection prioritizes initial code,
final code, or a declared combination.

**Why before the run:** changing the criterion after seeing results would allow
the data to determine both the rule and the winner.

## 4. Define the Samples

**Current position:** the population builder selects one accepted C program for
each of 3,265 eligible problems. Selecting a capped two or three programs per
problem is still under consideration.

**Decision needed:**

- programs selected per problem;
- prompt-selection sample size;
- final-evaluation sample size;
- confidence or precision target;
- split and sampling seeds;
- stratification, exclusions, and deterministic reserve problems.

Prompt-selection and final-evaluation sets must be disjoint by problem.

## 5. Freeze Judge Eligibility and Coverage

**Current position:** execution and reporting work. Exact description-hash
mapping produced 1,763 AIZU matches, and mapped-suite prefetch retrieved 1,738
complete suites with 33,301 cases. The remaining population-wide check is
accepted-C baseline validation. The earlier 1,487-suite corpus used incorrect
numeric problem associations and is not experiment evidence. All 1,391
AtCoder problems still lack equivalent system-suite coverage.

**Decision needed:**

- whether every newly mapped and downloaded suite receives an accepted-C
  baseline pass before sampling;
- whether Judge eligibility is defined before sampling or checked during each
  experiment run;
- unavailable-suite replacement policy;
- handling or exclusion of special judges and non-unique outputs;
- whether AtCoder problems are excluded or reported with different coverage.

An exactly mapped and downloaded suite is a candidate, not automatically a
valid experiment unit. A problem becomes Judge-backed only after an accepted C
reference passes locally. Any exclusion or deterministic reserve policy must
be fixed before translation outcomes are observed.

## 6. Define Any Manual Inspection Protocol

**Current position:** the workbook supports automatic analysis and navigation
to source, attempts, reports, and agent interactions. It does not contain
reviewer-entry, blinding, scoring, or adjudication sheets.

**Decision needed:** only if manual coding will contribute research evidence,
define what analysts inspect, the rubric, assignment, capacity, and treatment
of disagreements. This protocol does not need to live in the automatic
analysis workbook.

## Improvements That Do Not Block the Design

- Token usage is extracted from both LangChain usage metadata and the
  OpenAI-compatible response metadata fallback. It must still be verified with
  the final benchmark provider because providers may omit usage information.
- Visible-suite review is model-based and cannot prove constraints absent from
  the C source. The implemented bounded review policy and disabled-suite counts
  must be reported as limitations.
- Workbook presentation can continue to improve as long as automatic field
  meanings remain stable. Any separate manual coding protocol must be frozen
  before it produces research evidence.
- Additional logs should be added only when they provide evidence not already
  available in structured artifacts.

## Recommended Order of Work

```text
choose model
  -> freeze prompts and winning criterion
  -> define samples and holdout
  -> freeze Judge eligibility and choose suite acquisition mode
  -> define manual inspection only if it will produce research evidence
  -> run a small end-to-end pilot
  -> freeze code, data, configuration, and analysis
  -> run prompt selection
  -> freeze one prompt
  -> run final evaluation
```
