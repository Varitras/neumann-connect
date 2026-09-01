# The gates and the guards

What protects this integration, what each guard holds, and what to do when one
turns red. Written for whoever changes this code next - usually somebody with
no memory of why any of it is here.

## Run everything

```sh
.github/scripts/check.sh
```

Ruff, the full test suite, a compile pass, dead code and the mutation run, in
that order, stopping at the first failure.

The suite is **Linux-only**: `pytest-homeassistant-custom-component` imports
`homeassistant.runner` while collecting, which imports `fcntl`. Run it under
WSL2 or in CI, never native Windows.

```sh
python -m pytest tests/ -q          # everyday run, e2e deselected
python -m pytest tests/ -q -m e2e   # only the full Home Assistant boots
python -m pytest tests/ -q -m ""    # everything - mandatory before a release
```

## Why a mutation run

A passing test proves nothing on its own, and neither does a counter-check:
one that patches a line the code no longer has, or whose `-k` expression
selects none of the tests it means to check, reports "passed" without having
checked anything.

So `.github/mutations/plan.json` describes deliberate breakages and
`.github/scripts/mutate.py` checks that a named test actually fails for each.

A mutation that **survives** means the code was broken and the suite stayed
green: the test is decorative, or a guard has gone blind. The first run found
one immediately - `test_a_device_without_a_serial_writes_nothing` passed with
the write guard removed, because it only ever read back through a loader that
carries its own guard.

When you add behaviour worth keeping, add a mutation. When you move code, the
`find` fields move with it - `test_mutation_harness.py` fails on every
ordinary run if they do not.

## The guards

Structural tests that fail on a shape rather than a value. Each exists because
the thing it prevents actually happened here.

| Guard | Holds |
|---|---|
| `test_budgets.py` | No module grows past its ceiling, no function past its complexity ratchet |
| `test_comment_narration.py` | No comment merely restates the code it sits on |
| `test_constant_owners.py` | No constant is defined in two modules |
| `test_device_writes.py` | Every button press claims the device before writing |
| `test_log_privacy.py` | No log call hands out a serial number in full |
| `test_mutation_harness.py` | The mutation run fails loudly instead of reporting a breakage it never applied |
| `test_guards.py` | Every guard is listed, scans a real directory, and is not pinned to one file |

## When a budget turns red

`test_budgets.py` freezes size and complexity. Two rules, on purpose:

**Lines are a ceiling.** They move on almost every change, so the test only
asks that a module not grow past its entry. Modules under `LINE_LIMIT` (500)
need no entry.

**Complexity is a ratchet - an exact match.** It changes rarely, and when a
function does get simpler that progress is written down rather than left as
headroom for the next person to spend.

| Message | Meaning | What to do |
|---|---|---|
| module over budget | a file grew past its entry, or past 500 lines without one | Split it. If the growth is warranted, raise the entry **in the same commit** so the decision is visible in the diff. |
| budget far above the real size | a module shrank | Lower the entry to today's count. |
| function over budget | undeclared complexity | Cognitive complexity counts **nesting**: an early return or a guard clause usually helps more than extracting a helper. |
| budget out of step | a function got simpler, was renamed, or is gone | Set the entry to the current value, or drop it. |

The measure is Cognitive Complexity (Campbell / SonarSource), implemented in
`complexity.py` and calibrated against SonarQube Cloud: Sonar reports 35 for
`_read_lines_until_settled`, and so does this. `COMPLEXITY_LIMIT` is 15,
SonarSource's default.

## Adding a guard

1. **Scan the package, never one file.** `PACKAGE.glob("*.py")`, not a named
   module. A pinned scan goes blind the moment code moves - and a blind guard
   is worse than none, because the suite stays green. A guard left pointing at
   a package path that does not exist scans nothing and reports green for the
   same reason - `test_every_guard_scans_a_real_directory` catches both.
2. **Prove the guard can fail.** Feed the detector the exact shape it exists to
   catch - ideally the verbatim line from the incident, as
   `test_the_scan_catches_the_line_it_was_written_for` does.
3. **List it in `GUARD_FILES`.** A guard nobody lists is a guard nobody knows
   to keep.
