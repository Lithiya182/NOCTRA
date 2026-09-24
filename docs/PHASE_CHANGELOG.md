# NOCTRA Phase Changelog (Phases 0–15)

Roll-up of `docs/PHASE_REPORTS/phase_*.md` + git history.  
**Final suite**: 90/90 passed @ `38ab7cc` (pushed).

| Phase | Report file | Status label | Anchor commit / note |
|------:|-------------|--------------|----------------------|
| 0 | phase_0.md | OPERATIONAL — VERIFIED | Tag `noctra-baseline-pre-master-build`; baseline suite recorded |
| 1 | phase_1.md | OPERATIONAL — VERIFIED | Fixed 4 static row-count failures + polygons fixture |
| 2 | phase_2.md | OPERATIONAL — VERIFIED | FIRMS scheduler env gate; provenance helper + tests |
| 3 | phase_3.md | OPERATIONAL — VERIFIED | Thermal formula regression lock |
| 4 | phase_4.md | OPERATIONAL — VERIFIED | Classifier edge-case tests (no rule changes) |
| 5 | phase_5.md | OPERATIONAL — VERIFIED | Analyst notes + append-only `alert_reviews` |
| 6 | phase_6.md | OPERATIONAL — VERIFIED | Imagery panel UI + feedback endpoints |
| 7 | phase_7.md | OPERATIONAL (POC)* | Sentinel-2 STAC acquisition; 31 chips after Phase 13 cleanup (*report header says VERIFIED; capability matrix uses POC for thin geography) |
| 8 | phase_8.md | RESEARCH / EXPERIMENTAL | Classical CV RF (not CNN); P=0.25; N_test_pos=2 |
| 9 | phase_9.md | OPERATIONAL (POC) | Fusion; 19/31 conflicting |
| 10 | phase_10.md | RESEARCH / EXPERIMENTAL | Retrain ran; Δ=+0.0000 honest null |
| 11 | phase_11.md | RESEARCH / EXPERIMENTAL | Contextual bandit; heuristic proxy; 0 human rewards |
| 12 | VALIDATION_REPORT.md | OPERATIONAL — VERIFIED | Independent validation 83/83 at `851f73c` (superseded counts) |
| 13 | phase_13.md | OPERATIONAL (POC) | API key auth + SOS rate limit; `87924e4`, `d7f7015` |
| 14 | phase_14.md | OPERATIONAL (POC) | UI polish `3a0f517`; imagery static + click-to-locate browser-fixed `38ab7cc` |
| 15 | phase_15.md | OPERATIONAL — VERIFIED | This documentation pass: A-to-Z report, PPT map, changelog |

## Git timeline (abbrev.)

```
38ab7cc [Phase 14] Fix imagery static serving and alert click-to-locate — 90/90 passed  ← HEAD (pushed)
3a0f517 [Phase 14] Demo hardening — UI evidence badges, RL priority cards — 86/86
d7f7015 [Phase 13] Purge stale imagery, frontend API key disclaimer
87924e4 [Phase 13] Security & deployment hardening — 86/86
851f73c [Phase 12] Independent validation pass — 83/83
90ee9f7 / 16f744d / 2a33bd2 … [Phase 11] bandit + disclaimers — 83/83
897bb82 / 2e3709b [Phase 10] active learning — 80/80
861fbd9 [Phase 9] fusion — 77/77
6727331 / 98089ca [Phase 8] visual classifier — 73/73
3dd1016 [Phase 7] Sentinel-2 STAC — 70/70
2943964 [Phase 6] frontend feedback — 67/67
638d039 [Phase 5] human review — 65/65
355b196 [Phase 4] — 61/61
986704e [Phase 3] — 56/61 lineage
… Phase 0–2 baseline and foundation
```

## Incidents logged

1. VAPID private key once committed → purged via history rewrite (Phase ≤4 era); Phase 13 re-scan clean.
2. Phase 14 first pass claimed demo-complete but browser testing found broken imagery static route + missing click-to-locate → fixed in `38ab7cc`.
3. Several capabilities **downgraded** mid-build (visual “CNN” → classical CV; bandit → heuristic proxy; active learning Δ=0 reported as-is).
