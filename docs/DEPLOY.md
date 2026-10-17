# Deployment checklist (Render + Supabase)

No real value is written in this file. Keep it that way: secrets live only in Supabase, in Render's
environment settings and in your local `.env` (which is git-ignored).

## 1. Render service

- **Start command:** `gunicorn app:app --workers 1 --threads 4 --timeout 120`
- **Why one worker process:** the state of a run (progress, result, preferences, class sizes) is held in the
  memory of the process. With two worker processes a browser could poll a process that never saw the run.
  Threads share that memory, so four threads are fine.
- **Known limits of this design** (also in the README):
  - A restart, a deploy or a free-tier sleep loses a running job. Start the run again.
  - Two chairpersons of one department share one run state. A second run of the same department is refused
    while one is running; whoever finishes last owns the shown result.
- CP-SAT uses one search worker per CPU, at most 8, and no more than the container's CPU quota (read from
  `/sys/fs/cgroup/cpu.max`, or `cpu.cfs_quota_us` and `cpu.cfs_period_us` on cgroup v1), so a small instance is not oversold.
- **Solver time (optional environment variables, seconds):**
  - `ATLAS_CP_SAT_TIME_LIMIT`: default budget of a run that does not ask for one (default 30, never above the ceiling).
    The dashboard sends the department's saved Solver Settings value, so that is what a browser run uses.
  - `ATLAS_CP_SAT_MAX_TIME_LIMIT`: hard ceiling for every run, including the browser setting (default 40, allowed up to 120). The Solver Settings slider goes up to 120 s (default 45 s) and the server clamps it to this ceiling, so set `ATLAS_CP_SAT_MAX_TIME_LIMIT=60` on Render to let the slider reach 60 s.
  - gunicorn's `--timeout 120` does not limit the background job, which runs in its own thread. Keep a demo run under
    about 60 s anyway.
  - If CP-SAT stops on its limit with groups still uncovered (slow free CPU), a repair step completes them without
    changing any professor CP-SAT chose, and the run shows a warning with the number of repaired groups.
- **Environment variables** (names only, see `.env.example`): `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`.

## 2. Rotate the secrets (an older zip once contained a real service key)

1. Supabase dashboard, Project Settings, API: roll the **service role key**. Roll the **JWT secret**
   (this also invalidates every signed-in session, so everyone signs in again).
2. Copy the new values into Render, Environment. Never into a chat, a ticket, a file in the repo or a commit.
3. Redeploy on Render and sign in once as a chairperson to confirm `/runs` and `/audit` answer.
4. Update your local `.env` the same way.
5. Delete the old zip and any copy that still holds the old `.env`.

## 3. Confirm the repository is clean

```bash
git check-ignore -v .env              # must print the .gitignore rule that ignores it
git log --all --oneline -- .env       # must print nothing: .env was never committed
python -m pytest tests/test_part18.py -q -p no:cacheprovider   # runs the secret scan
```

If `git log --all -- .env` prints a commit, the secrets in it are public history: rotating them (step 2) is then
mandatory, not optional, and the history should be rewritten before the repository is shared.

## 4. Before the demo

- [ ] Run `db/schema.sql` in the Supabase SQL editor (idempotent; adds the Part 24 period columns).
- [ ] `db/rls_tests.sql` passes on a scratch project.
- [ ] `python -m pytest tests -q -p no:cacheprovider` is green.
- [ ] Open the site once with the network tab: no request goes to `fonts.googleapis.com` or `fonts.gstatic.com`.