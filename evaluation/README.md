# Evaluation protocol

One command regenerates every number of the results chapter:

    python scripts/evaluate.py --out evaluation          # full protocol (use --jobs N to run seeds in parallel)
    python scripts/evaluate.py --quick                   # smoke test only, not for the paper

Outputs: `results.csv` (one row per run) and `summary.md` (mean, sample standard deviation and 95% confidence interval).
Both are generated; this folder keeps only this file in the repository.

## Design

- **Cells.** 5 departments (IT, CS, MB, ES, MedB) x 2 semesters = 10 cells. Each cell uses the standard test faculty pool of
  `tools/faculty_pool.py::dept_faculty` (10 pseudonymous professors, 2 or 3 tags each, every tag covered, Mon to Thu,
  24 regular and 30 absolute maximum units) and the department's own curriculum, class sizes and rooms.
- **Methods**, each with N seeds (default 10, `--seeds`):
  1. `random_baseline`: random-feasible greedy. Groups in random order, each to a random qualified professor and random free
     slots. Only the hard rules decide what is allowed (availability, one meeting per professor, block and room per slot,
     absolute load cap).
  2. `cp_sat`: CP-SAT assigns professors under the hard rules and balances load.
  3. `cp_sat_ga`: the CP-SAT schedule, then the GA improves times and rooms for preferences, room capacity fit and building
     compactness. The GA never changes a professor. Both CP-SAT rows of a seed come from the same CP-SAT run.
- **Deterministic mode.** One CP-SAT worker, a deterministic-time budget (default 15, the smallest budget that covered every group in
  trials; `--cp-time`), no wall-clock cut-off in the GA, and one seed per run that drives CP-SAT, the GA and the baseline. The same
  seed gives the same schedule on any machine load. Runtime is the one non-reproducible column. GA defaults: 50 generations,
  population 20, mutation 0.15, crossover 0.8.
- **Preferences.** Synthetic and pseudonymous, the same for every method (`standard_preferences`): professor i prefers morning,
  afternoon or evening in turn, and every second professor avoids one weekday. Only the GA optimizes them, so the preference
  score of the baseline and of CP-SAT is incidental.

## Metrics (per run)

Definitions are the Part 19 ones in `services/analytics_service.py`, computed over all professors and in load units.

| Column | Meaning |
|---|---|
| `coverage_pct` | course groups with a professor / all groups |
| `violations` | hard-rule violations from `validate_schedule` (must be 0); a group nobody could staff (`UNCOVERED`) is not counted here, it lowers `coverage_pct` |
| `jain`, `cv`, `min_load`, `max_load`, `zero_load` | Jain's index, std/mean, lowest and highest load, professors with no load |
| `primary_tag_match_pct` | course groups whose tag equals the professor's first tag (elective-only groups excluded) |
| `preference_score` | the GA preference term (Part 21), computed with the standard preferences |
| `capacity_penalty` | sum of the negative room capacity terms (lower is better) |
| `building_switches` | sum over professor-days of (distinct buildings - 1) |
| `runtime_sec` | wall-clock seconds (`cp_sat_ga` = CP-SAT plus GA) |

## Scenarios (the classmates' problem)

Started from the standard pool, N = 3 seeds (`--scenario-seeds`), all cells, same metrics:
`remove_one` (first professor removed), `days_1` and `days_2` (first professor available only Mon, or Mon and Tue),
`add_with_tags` (a new professor with the department's first two tags) and `add_no_tags` (a new professor with no tags, who can
only take electives). A scenario can lower coverage when a tag loses its only holder; that is reported, not hidden.

## Statistics

Per cell: mean, sample standard deviation (n - 1) and a 95% confidence interval from Student's t over the seeds. The overall table
pools every run of a method across the 10 cells, so its SD includes the spread between cells.

## Run time

Serial, one CPU: roughly (10 cells x 10 seeds + 5 scenarios x 10 cells x 3 seeds) tasks of about 20 to 30 seconds each, so plan for
a few hours, or use `--jobs`. `--quick` takes a few minutes.