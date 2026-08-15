# Feature Brief: Canonical Flutter Guidance And Lints Review

<!-- hard-eng-state:v1 -->
- state_version = 1
- plan_id = canonical-flutter-guidance-and-lints-review-69a82d79
- lifecycle_status = green
- approval_status = approved
- approval_fingerprint = sha256:0ad6b3af904cd35a27299acf7bf78fd5df4d91c784120832d524cbbb496a0b57
- approval_provenance = ready-to-build
- green_artifact = sha256:2a0d8a55629741b4059fd8768af2cab4c1ff1fe1cdf7dbe7644549040ac78d60
- active_slice = none
- completed_slices = S-1,S-2,S-3,S-4
- next_action = Deliver the two authorized repository updates after final diff, privacy, sync, and CI checks.
- replan_reason = none
<!-- /hard-eng-state -->

## Outcome
- Both canonical repositories contain generic, privacy-safe, current Flutter guidance and lint enforcement for the reusable lessons recorded in the supplied thread.
- The guidance repository owns the compatibility matrix, E2E, persistence, networking, testing, scenario-receipt, and validator contracts.
- The lint repository owns executable diagnostics and fixtures for dependency overrides, unsafe persisted-map restoration, and any host-driver import rule that evidence supports.
- Every accepted rule has a behavioral fixture, every new instruction has a validator or eval, and both repositories have complete local proof before delivery.

## Non-goals
- Copying application, customer, person, service, route, database, log, screenshot, or production identifiers from the source thread.
- Publishing packages, marketplace releases, tags, deployments, or writing to live customer or production systems.
- Replacing existing useful guidance or unrelated dirty lint work without evidence.
- Making a consuming Flutter application conform to an unverified dependency family.
- Treating a passing command, screenshot, wrapper exit code, or static text search as proof of runtime behavior by itself.

## Material decisions
- Preserve the modified lint paths already present in the selected checkout and reconcile their intent before adding changes.
- Keep version truth in `skills/building-flutter-apps/references/core-stack.md`; use exact versions when the generator family requires one analyzer family, and never use dependency overrides to force compatibility.
- Use the shared analyzer-13.3.0 plugin family with `riverpod_lint 3.1.8`; reject analyzer 14.1.0 for this combined analysis-server setup because the real smoke test cannot solve it.
- Use official Flutter, Dart, analyzer, pub.dev package, and tool documentation checked against the local resolved toolchain. Record source URLs, versions, and research dates in the compatibility reference.
- Keep `dart run build_runner build` flag-free as the only active generation command.
- Keep the plan generic. Use invented placeholders such as `<PROJECT_ID>` and `test@example.invalid` in examples.
- No visual surface is changed.
- ux_reference = n/a
- ux_reference_sources = n/a

## Acceptance examples
- Given a Flutter app uses the documented stack, when its declared package family is solved without overrides, then the disposable fixture generates Riverpod, Freezed, Hive, JSON, and GoRouter code, analyzes, tests, and builds one supported target.
- Given `pubspec.yaml`, `pubspec_overrides.yaml`, a workspace member, or relevant lock evidence contains a dependency override, when the lint/check runs, then it reports the owning file and dependency without exposing private values.
- Given a persisted value is `Map<dynamic, dynamic>`, when it is restored, then the documented and tested path checks map shape, validates every string key, creates a new typed map, and rejects malformed values without silently clearing valid data.
- Given a Flutter Driver host file imports Flutter UI or rendering code directly or transitively, when the host boundary check runs, then it fails with the host file and forbidden import path.
- Given an E2E phase is marked clean-state or preserved-state, when the scenario runs, then the correct app-data container and install checks happen before and after launch or restart, and reinstall flags cannot create a false pass.
- Given a modal is dismissed before another modal reuses its selector, when the driver continues, then it waits for the old key to be absent and the duplicate-key regression fixture fails if that wait is removed.
- Given a native file picker, share sheet, or permission prompt is opened, when the operation completes, then the guidance requires platform proof, valid accepted types, and an application pending state until native completion.
- Given a scenario claims completion, when its manifest is evaluated, then totals are computed from unique parent/child IDs, direct assertions and source-of-truth checks have receipts, cleanup is verified, and unknown names fail.
- Given an operation returns an accepted terminal status, when retry classification runs, then it avoids retry and incident reporting; retryable and terminal failures remain distinct and widgets do not own backend classification.
- Given either repository is delivered, when its complete tracked and untracked diff and privacy scan are reviewed, then no source-thread project or customer data, hidden suppressions, skipped required tests, or unknown required CI result remains.

## Affected canonical areas
- `building-flutter-apps/skills/building-flutter-apps/SKILL.md` and directly linked references.
- `building-flutter-apps/evals`, `tool/` validators, fixtures, manifests, version metadata, and CI checks.
- `flutter_skill_lints` dependency/configuration rules, analyzer plugin registration, persistence-map rule, host-driver boundary if supported by the current analyzer API, inventories, fixtures, and integration tests.
- Both repositories' README, changelog/version surfaces, workflow gates, and privacy checks where current truth changes.

## Risk and rollback
- risk_level = critical
- critical_overlay = S-2 persisted-map restoration rule + safe-normalization fixtures + corrupt-value rejection proof; owner = lint rule and Hive guidance; recovery = revert only that rule/docs slice if the accepted safe behavior cannot be proven without affecting existing diagnostics.
- rollback = keep the existing dirty lint work intact, revert only this feature's reviewed commit(s), and rerun the pre-change repository gates; no generated or live data is mutated.
- deferred = none
- blocked_on = none; the preserved lint worktree now has a zero-finding full Decimate scan.

## First vertical slice
- S-1 = verified compatibility matrix + single version owner + flag-free generator guidance + negative override fixture contract.
- proof = official-source receipts + local dependency solving probe + validator/fixture RED/GREEN evidence + affected repository checks.
- S-2 = dependency-override and persisted-map protections with positive/negative fixtures.
- S-3 = host-driver, E2E state, gesture/modal/native-system, scenario-receipt, logging, and networking guidance with behavioral validators/evals.
- S-4 = reconcile inventories, metadata, privacy, docs, full gates, diff review, commits, push, and required CI proof.
