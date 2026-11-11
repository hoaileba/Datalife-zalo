# MAP: DataMate v4 code

One flow: **read data → catalog → prompt → model writes a program → sandbox runs it → check → answer**.
All code is in `src/datamate/`. Lower layers never import higher ones (`tests/test_structure.py`).

```
runner ─┬─ solve ─┬─ prompt ── answer ── helpers
        │         ├─ sandbox ── worker ─┬─ helpers, program, shape
        │         └─ catalog ── notes, data ─┬─ layout ─┬─ grids ── values
        │                                    │          └─ totals ── values
        ├─ llm                         ├─ columns ── values
        │                              └─ grids
        ├─ eval
        └─ config
replay ── sandbox, data, answer
```

| Module | Does | Key names |
|---|---|---|
| `values.py` | Cell values: fold/nfc, numbers (`1.234.567 đ`, `19tr990`), quantities, dates | `parse_number`, `parse_qty`, `parse_datetime` |
| `grids.py` | Read CSV/XLSX/SQLite into grids; header row (and a two-row header), labels, total labels, partition files/sheets of one table (period tokens in file and sheet names, same columns in any order; sheets named otherwise stay apart), table names | `read_business`, `find_header`, `sub_header`, `labels_of`, `partition_groups`, `table_name` |
| `layout.py` | Rows around the header: data vs layout rows (blank, repeated header, totals by label or by arithmetic, notes after the data, signature footers, section rows → `__section`; a heading or footer is shaped unlike its column's values), two-row header, text above the header, partitions of one table (sheets with other names only when their dates do not overlap), fill-down of group cells (never on a list whose text column identifies every row); invoice rows above their lines (fill-down groups, or runs of one key) move their sums to `<col>__group_total` | `body_rows`, `sub_header`, `partition_groups`, `title_lines`, `fill_groups`, `run_totals` |
| `totals.py` | Totals by arithmetic, linear time (prefix sums + hash of the block start): rows sparser than every line of the block they sum (above or below; one-line blocks when laid out like the totals found), whose layout is mostly totals; a text that recurs only on rows equal to the sum since its last occurrence is a learned total label. `group_totals`: a group's first row laid out unlike its lines and holding their sum (an invoice row) | `sum_totals`, `recurring_totals`, `group_totals`, `move_totals` |
| `columns.py` | Column typing from content; the decimal mark and the day/month order a column's own cells show | `type_column`, `to_series`, `decimal_mark`, `date_order` |
| `data.py` | Grids → pandas tables in sandbox dtypes + column profiles (with dropped-row examples, text above the header); calendar table; disk cache | `load_business`, `Business`, `build_tables` |
| `rules.py` | Rulebook as line units keyed by their words, numbers and operators (case, tone placement, punctuation, markdown ignored). Against the standard lines (the train rulebook, stored in `assets/cookbook_train.yaml`): changed/new lines (and every line under a new heading), the standard lines that are gone, or a rewrite (full text, whole cookbook) | `units`, `key`, `changes`, `compare`, `load_cookbook` |
| `notes.py` | Noise measured on the data for `catalog.data_notes`: same-named keys vs their master table, values written several ways (case/spaces/missing accents), codes with several names, items in several units (units = words written after a number) | `data_notes` |
| `catalog.py` | Lean catalog for the prompt (tables, columns, README, rulebook pointer, `rulebook_changes`); values the question mentions | `build_catalog`, `lookup` |
| `helpers.py` | `dm` helpers for agent code; `TolerantFrame` (accent/case-tolerant column reads and writes). Ambiguous calls raise with the fix (top without a clear code, between on a non-date column) | `norm`, `to_num`, `to_date`, `between`, `dedup`, `drop_groups`, `top`, `factors` |
| `names.py` | dm.name_key: one key per name written several ways (case, spaces, punctuation; an unaccented spelling with its ONE accented form; other accents stay other names) | `name_key` |
| `windows.py` | Calendar windows for dm (day, days_back, week, month, quarter, year; inclusive; refs read like the data; raises on unreadable refs, bad week_start, empty windows) | `week_range`, `month_range`, `days_back` |
| `program.py` | Broken `print` lines skipped, failing prints only warn; error line location | `tolerant_compile`, `error_location` |
| `shape.py` | `result` → JSON-safe value (DataFrame/Series/list/dict shapes), in the worker | `shape`, `ShapeError` |
| `worker.py` | Child process: load tables, run the program, return result or error | `run`, `MARKER` |
| `sandbox.py` | Start the worker with memory/CPU/file/time limits (no bwrap: works in Docker) | `execute`, `Limits`, `Execution` |
| `answer.py` | Validate result against answer_type, submission format, pre-submit checks | `finalize`, `issues`, `submission_line` |
| `prompt.py` + `assets/prompt.md` + `assets/cookbook_train.yaml` | System prompt of a set (instructions + cookbook: one verified recipe per standard rule, `cookbook_train.yaml` = every train rulebook line with the recipe that carries it; recipes of the lines a set changed or dropped are left out, or kept and marked when another recipe cites them), user message (catalog first: prefix cache), JSON schema (retry turns start with `diagnosis`), action parsing/repair | `system_prompt`, `cookbook`, `messages`, `response_format`, `parse_action` |
| `llm.py` | OpenAI-compatible client (vLLM, DeepSeek, OpenRouter), streamed; stops repetition and comment floods; `Reply.meta` (request, response ids, timings, retried errors) | `LLM.chat`, `Reply` |
| `solve.py` | ≤ 4 turns for one question; auto-submit on a clean result; abstain on failure | `solve`, `Context`, `Outcome` |
| `eval.py` | Local score, strict format check, code-flow health | `score`, `format_ok`, `health` |
| `runner.py` | All questions, 2 workers, time budget, rulebook as pointer + changed lines, `submission.jsonl` + `logs/` + `summary.json` + run snapshot (`config.yaml`, `system_prompt.md`) | `run`, `main` |
| `replay.py` | Re-run logged programs with current host code (no model calls) | `replay` |
| `config.py` | `config.yaml` and `.env` | `load_config`, `load_dotenv` |

Data flow of one question: `runner.one` → `Businesses.get` (data + catalog, cached) → `solve` → per turn
`prompt.messages` → `llm.chat` → `prompt.parse_action` → `sandbox.execute` → `answer.finalize` + `answer.issues`
→ submit, or the error/result goes back as the next user message.

Outside `src/`: training data tools in `gen/` (see `docs/PLAN_TRAINDATA.md`); teacher runs `gen/teacher.py` (threads,
one record per question), `gen/teacher_stats.py` (CSV + stats), prompt review `scripts/prompt_md.py`
(guide: `docs/TEACHER_GEN.md`).
