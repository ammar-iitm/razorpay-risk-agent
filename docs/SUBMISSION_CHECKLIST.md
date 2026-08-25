# Pre-submission checklist

Small, easy-to-forget items to handle before the final submission (Day 10 /
final day per the tracker) — not part of any single day's core build work,
so they'd otherwise get lost between now and Sep 5.

- [x] ~~Fix git commit author email.~~ Done Aug 25 — global `user.name`/
      `user.email` set correctly, most recent commit's author fixed with
      `--amend --reset-author`, force-pushed with `--force-with-lease`
      (needed since the earlier large-file fix had already pushed the
      pre-amend version). Confirmed clean on GitHub.
- [ ] Flip the GitHub repo from private to public (or confirm the buildathon
      submission form's exact visibility requirement first).
- [ ] Delete or confirm `.gitignore` is still catching `data/`, `.venv/`,
      `*.db`, and `day5/pr_curve_results.csv` before the final push — worth
      a last `git status` sanity check given how many times a large/secret
      file has almost snuck in during this build (see `BUILD_LOG.md`).

*(append more items here as they come up — this file exists so nothing gets
lost to chat history between now and submission)*
