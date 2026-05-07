# Building-Flutter-Apps Skill — Full Audit Report
**Date:** 2026-05-08 · **Scope:** all 28 files (~7.5K LOC) · **Method:** 5 parallel persona agents (flutter-auditor, drift-hunter, online-verifier, junior-dev, staff-engineer) cross-checking internal consistency + verifying claims against pub.dev / package changelogs.

---

## TL;DR

Doc set is **technically strong at the file level** but has **systemic seam defects**: two files teach contradictory patterns for the same concept, several code blocks won't compile, one package version pin is suspect, and the architecture chain (`Datasource → Repository → Notifier`) is violated by the very example that teaches Hive persistence.

**Biggest single risk:** `references/hive-persistence.md`'s `OrderRepository` example teaches an unmockable, interface-skipping, layer-bypassing pattern that contradicts `architecture.md` and `testing.md`. Anyone copying this pattern fails the skill's own testability gate.

**Highest leverage fixes:** 4 blockers below. Fixing them resolves ~60% of downstream drift.

---

## P0 — Blockers (will produce broken code if copied)

### B1. `riverpod-codegen.md:120` — sync call to async loader inside `build()`
Calling `_loadProduct(productId)` synchronously from `build()` writes `state.copyWith(...)` before `build()` returns → runtime: *"Bad state: Tried to read state of uninitialized provider"*.
**Fix:** `Future.microtask(() => _loadProduct(productId));`

### B2. `architecture.md:224` — missing cast on `fromJson`
`ProductModel.fromJson(json)` where `json` is `Object?` (return of `_http.get`). Runtime `TypeError`.
**Fix:** `ProductModel.fromJson(json as Map<String, dynamic>)`

### B3. `riverpod-codegen.md:266` — wrong cast type
`item as Map<String, Object?>` — `json_serializable` generates `_$TodoFromJson` expecting `Map<String, dynamic>`. Compile/runtime mismatch.
**Fix:** `item as Map<String, dynamic>`

### B4. `common-patterns.md:39` — unbounded family cache
`@Riverpod(keepAlive: true)` on family `programById` keeps every unique `id` arg forever. Memory leak.
**Fix:** drop `keepAlive: true` (use plain `@riverpod`); rely on auto-dispose for family.

### B5. `extensions-utilities.md:344` — `Validators.compose` return type wrong
Declared `String?`, body returns a closure. Won't compile.
**Fix:** `String? Function(String?)`.

### B6. `testing.md` — `.future` called on sync `Notifier`
`container.read(productProvider.future)` — `.future` exists only on `AsyncNotifier`. Throws.
**Fix:** `container.read(productProvider)` for sync; reserve `.future` for `AsyncNotifier`.

### B7. `architecture.md` — `productProvider.select((s) s.items)` missing `=>`
Broken Dart syntax in a teaching example.
**Fix:** `(s) => s.items`.

---

## P1 — Architectural contradictions (must resolve to keep skill coherent)

### A1. `hive-persistence.md` `OrderRepository` violates the canonical layer chain
- `OrderRepository extends _$OrderRepository` is a Riverpod **notifier** acting as repository.
- No `IOrderRepository` interface; no `HiveOrderDatasource`; domain entity stored directly in Hive.
- Contradicts `architecture.md` (interface required), `testing.md` (mockability), `services-and-singletons.md` (function-based providers for repos).
**Fix:** split → `IOrderRepository` (interface) + `HiveOrderRepository implements IOrderRepository` (concrete) + `HiveOrderDatasource` (box ↔ Hive model) + `OrderModel` (Hive type) ↔ `Order` (domain). Provider returns `IOrderRepository`. Mirrors the pattern shown in `architecture.md`.

### A2. Folder layout drift — three layouts taught simultaneously
- `architecture.md` prose: repositories bridge domain↔data.
- `architecture.md` diagram: `repository/` inside feature parallel to `data/`+`domain/`.
- `architecture.md` folder tree: `repositories/` as fourth sibling.
- `atomic-design.md` placement table: `features/x/widgets/`.
- `architecture.md` elsewhere: `features/feature_x/presentation/widgets/`.
**Fix:** pick ONE layout, codify in `architecture.md`, cross-link from every other file. Suggest:
```
features/<feature>/
  data/        (datasources, models, repository implementations)
  domain/      (entities, IRepository interfaces)
  application/ (notifiers, mutations)
  presentation/widgets/  (atoms..templates)
  presentation/screens/  (pages)
```

### A3. `atomic-design.md` vs `SKILL.md` — `ref.watch` rule conflict
- `atomic-design.md` Rule 3: "NEVER `ref.watch` in atoms, molecules, templates."
- `SKILL.md`: "Widgets MUST watch providers — NEVER prop drill."
- Templates sit in the gap with no resolution.
**Fix:** carve out templates as the **provider boundary** in `atomic-design.md`. Atoms/molecules: pure props. Templates/screens: provider entry points. Re-state in SKILL.md so the two rules compose.

### A4. Dual error model in `state-management.md`
Early notifiers use `state.copyWith(error: e.toString())` (raw String). Later sections introduce `AppError` sealed hierarchy with no migration. Devs will mix both.
**Fix:** declare `AppError` the sole error type, replace raw-String examples, add rule: *"Always wrap caught error → `AppError`. Never store `String? error`."*

### A5. `Crash.error` call-site rule undefined
- `crashlytics.md` example calls `Crash.error` from a sync/data layer catch.
- `state-management.md` rules: catch lives in notifier only.
- Datasource catch policy unstated.
**Fix:** explicit rule in `crashlytics.md`: *"`Crash.error` is called from notifier-layer (or app boundary) only. Datasources rethrow; notifiers translate → `AppError` → `Crash.error`."*

### A6. `services-and-singletons.md` self-contradicts in 10 lines
Static-only `Crash` class directly references `FirebaseCrashlytics.instance`, but the same file's *"Not when"* table forbids static classes from touching Firebase.
**Fix:** either rewrite `Crash` as a Riverpod-provided service (`crashServiceProvider`) — keeping the static facade only as a thin shim — or update the *"Not when"* table to permit infrastructure-only static facades with a disclosed tradeoff.

### A7. `crashlytics.md` — facade↔backend wiring not shown
`ICrashBackend` interface and `ConsoleCrashBackend` example exist; nothing shows where `Crash.initialize(backend)` is called from `main()`.
**Fix:** add a `main()` wiring snippet identical to `SnackBarUtils.initialize` pattern.

---

## P2 — Online drift (claims vs primary sources)

### V1. `showcaseview: ^5.0.2` may not exist on pub.dev
`references/showcase-tours.md:11` pins `^5.0.2`. Latest confirmed stable on pub.dev: **5.0.1** (Oct 2025). `pub get` may fail for users.
**Fix:** verify 5.0.2 release; if not present, downgrade pin to `^5.0.1`.

### V2. `riverpod-codegen.md` — `riverpod_sqflite` not publicly released
Offline-persistence section cites `riverpod_sqflite` as the official package. **No stable release on pub.dev as of 2026-05-08.**
**Fix:** flag the entire section *"not yet publicly available — preview API"*; remove `riverpod_sqflite` as a dependency suggestion until released.

### V3. GoRouter 17.0 breaking change undocumented — `notifyRootObserver`
GoRouter 17.0.0 made `ShellRoute` notify root observers by default. Param `notifyRootObserver` added to opt out. Not in `common-patterns.md` or `architecture.md`.
**Fix:** add a callout in the GoRouter section: *"In 17.x, `ShellRoute` propagates navigation events to root observers. Pass `notifyRootObserver: false` to opt out."*

### V4. Hive CE `IsolatedHive` (2.19.x) missing entirely
`hive-persistence.md` teaches single-isolate Hive. `IsolatedHive` API (background-isolate persistence) added in 2.19.x is absent.
**Fix:** add `## IsolatedHive` subsection — when to use it, the safety warnings the package emits.

### V5. ShowcaseView 5.0.0 removed `height` / `width` from `Showcase` widget — migration note missing
Breaking #541 in v5.0.0. Pre-5 users migrating will hit silent layout errors.
**Fix:** add migration callout in `showcase-tours.md`.

### V6. `Mutation<T>()` is **experimental** — caveat missing in `SKILL.md`
`riverpod-codegen.md` correctly labels Mutation experimental. `SKILL.md` anti-patterns table recommends `Mutation<T>()` as the settled fix without the experimental flag.
**Fix:** suffix the SKILL.md row with `(experimental — API may break)`.

### V7. `riverpod_lint: 3.1.4-dev.3` pinned in `references/analysis_options.yaml`
Pre-release pin shipped in copy-paste config. Users will silently adopt a dev release.
**Fix:** promote to latest stable, OR add an inline comment `# pre-release; pin to latest stable before shipping`.

### V8. `json_serializable: 6.13.0` exact-pin rationale (analyzer 9 vs 10) is stale-prone
Reasoning given in `freezed-sealed.md` is correct as written but the analyzer 10 ecosystem is moving. If Riverpod/Hive generators now support analyzer 10, the pin reason no longer applies.
**Fix:** re-run `dart pub deps` on a fresh project; either lift the pin or refresh the rationale.

### V9. Freezed 3.2.5 requires Dart SDK ≥ 3.8 — not surfaced in setup snippet
`freezed-sealed.md` setup omits the Dart SDK floor. Users on older SDKs hit confusing solver errors.
**Fix:** include `environment: { sdk: '>=3.8.0 <4.0.0' }` in the example.

### V10. Riverpod 4.0 forward signal (changelog) not relayed
Riverpod 3.x official changelog: *"It is quite possible that a 4.0.0 will be released."*
**Fix:** one-line forward-compat note in `riverpod-codegen.md` setup so users plan for short-lived 3.x.

### V11. Crashlytics — note `runZonedGuarded` is the older pattern
The doc's 3-hook pattern (`FlutterError.onError` + `PlatformDispatcher.onError` + `Isolate.addErrorListener`) is current best practice. Add explicit note that `runZonedGuarded` is **legacy**, not recommended.

---

## P3 — Cross-doc drift (internal contradictions, version mismatches)

| # | Issue | Files | Fix |
|---|---|---|---|
| D1 | `flutter_skill_lints` version `^0.2.0` in doc snippet, no version in YAML | `analysis-options.md` vs `references/analysis_options.yaml` | Align: pin in both or pin in neither |
| D2 | `hive_ce`, `hive_ce_flutter` listed in `hive-persistence.md` Core Stack, missing from `CONTRIBUTING.md` Package Versions | `hive-persistence.md` ↔ `CONTRIBUTING.md` | Add to CONTRIBUTING.md |
| D3 | `freezed: ^3.2.5` (caret) vs `freezed: 3.2.5+` (CONTRIBUTING.md format) | mixed | Pick one constraint syntax repo-wide |
| D4 | `freezed_annotation: ^3.1.0` not in CONTRIBUTING.md | `freezed-sealed.md` ↔ `CONTRIBUTING.md` | Add it |
| D5 | `SKILL.md` Core Stack table has no version column; `README.md` does | SKILL.md ↔ README.md | Add version column to SKILL.md (SSOT = README.md) |
| D6 | `evals/evals.json` (25 cases) vs `evals/trigger-eval.json` (20 entries) | evals/* | Align counts or document asymmetry |
| D7 | `build_runner watch -d` shorthand in SKILL.md vs `--delete-conflicting-outputs` everywhere else | SKILL.md vs references/* | Note `-d` = `--delete-conflicting-outputs` once |
| D8 | `json_annotation: ^4.11.0` (caret) vs `json_serializable: 6.13.0` (pinned) — mixed style in same file | CONTRIBUTING.md | Use caret for both, or document why json_serializable is pinned (per V8 above) |
| D9 | `hive_ce_generator: 1.11.0` exact pin vs Core Stack table (no constraint shown) | CONTRIBUTING.md ↔ hive-persistence.md | Show same constraint syntax both places |
| D10 | SnackBar rule re-stated across files without single SSOT | SKILL.md rule 15 vs others | Mark SKILL.md rule 15 as authoritative; replace re-statements with link |
| D11 | `riverpod_annotation` version absent from per-file pubspec snippets | references/* | Audit each setup block; ensure `riverpod_annotation: ^4.0.2` is shown |
| D12 | SECURITY.md "4.x supported" is ambiguous (skill version vs package version) | SECURITY.md | Clarify scope sentence |

---

## P4 — Clarity / new-hire pain points

| # | File:line | Confusion | Fix |
|---|---|---|---|
| C1 | `state-management.md` `_ensureRepository` | Missing `if (!ref.mounted) return;` after `await` — violates rule defined two sections above | Add the guard |
| C2 | `common-patterns.md` Route-Param Safety | Entire `persist→sync→navigate` block commented out — indistinguishable from disabled code | Wrap in `// ✅ DO:` block or convert to prose |
| C3 | `common-patterns.md` orphan `\| Real-time updates \|` row after a code block | No table header above; looks stray | Attach to correct table or delete |
| C4 | `mixins.md` `retryWithBackoff<T>()` | Body is one comment stub; new hire can't implement | Provide full implementation or remove |
| C5 | `riverpod-codegen.md` `final addTodoMutation = Mutation<void>()` declared at top-level | Where does this live? class? widget? file scope? | Show full class context |
| C6 | `showcase-tours.md` `AppShowcaseTarget` table | `disposeOnTap` constraint only in a separate later section | Duplicate as table column note |
| C7 | `common-patterns.md` `SearchNotifier` references `Debouncer` | No import path; new hire searches blindly | Add `// core/utils/debouncer.dart` inline |
| C8 | `freezed-sealed.md:267` non-constant defaults snippet | No enclosing class declaration → won't compile standalone | Add class header + closing brace |
| C9 | `performance.md:112` const Padding example | Uses non-const `child` variable inside const constructor — Dart rejects | Use a concrete const child (e.g. `SizedBox.shrink()`) |
| C10 | `crashlytics.md` `_prevFlutterHandler` / `_prevPlatformHandler` | Referenced but never declared on the `Crash` class in shown snippets | Add field declarations to the class snippet |

---

## P5 — Strategic / scope gaps

| # | Gap | Impact | Fix |
|---|---|---|---|
| G1 | No `references/networking.md` (HTTP setup, dio/retrofit, interceptors, retry, auth headers) | `architecture.md` references `http_service.dart` with zero coverage | Add it OR explicitly declare HTTP out of scope in `architecture.md` |
| G2 | No `references/forms.md` despite SKILL.md claiming form coverage | `extensions-utilities.md` only ships `Validators` composables; no `FormState` lifecycle, multi-field validation, or form-notifier integration | Add it OR remove form claim from SKILL.md |
| G3 | No tradeoff callouts | Atomic design's 6-level hierarchy is overhead-heavy for small apps; `keepAlive` providers leak unless explicitly disposed; codegen complexity | Add brief "When to skip atoms" + keepAlive memory warning |
| G4 | No end-to-end wiring diagram (Datasource → Repository → Notifier → Widget) | Each file shows its layer in isolation; reader has to assemble mentally | Add one Mermaid sequence diagram in `architecture.md` showing concrete types end-to-end |
| G5 | No i18n / theming / accessibility guidance | Standard senior expectations for a Flutter skill | Either add stub sections or explicitly scope-out |

---

## Recommended fix order

1. **Blockers (B1–B7)** — broken code in teaching examples is the highest-cost defect; fix first.
2. **A1 (Hive repository)** — fixing this single example closes the largest architectural gap; resolves A2 in part by forcing canonical layout.
3. **V1 + V7 (showcaseview pin, riverpod_lint pre-release)** — copy-paste failures users will hit immediately on `pub get`.
4. **A2 folder layout SSOT** — pick one, refactor all other refs to point at `architecture.md`.
5. **A4 + A5 error model + Crash call-site** — declare the rule explicitly; downstream files inherit consistency.
6. **D1–D12 version table normalization** — single pass, mechanical edits.
7. **V2–V6 + V8–V11 online drift** — version notes, migration callouts.
8. **C1–C10 clarity polish** — one editing pass per file.
9. **G1–G5 scope gaps** — decide in/out of scope; add stubs or update SKILL.md description.

---

## Verified-correct (no action needed)

- `flutter_riverpod ^3.3.1` matches latest stable (3.3.1)
- `freezed ^3.2.5` matches latest (Feb 2026)
- `go_router ^17.2.3` matches latest (5 days ago at audit time)
- `hive_ce ^2.19.3` matches latest
- `hive_ce_generator 1.11.0` matches latest
- `@riverpod` / `@Riverpod(keepAlive:true)` annotation usage — correct for 3.3.1
- Unified `Ref` (no `AutoDisposeRef` in 3.x) — correct
- `sealed class` + `@freezed` — matches freezed 3.2.5
- `@GenerateAdapters` / `reservedTypeIds` — matches hive_ce_generator 1.11.0
- Crashlytics 3-hook pattern — current best practice (more complete than legacy `runZonedGuarded`)
- `ShowcaseView.getNamed(scope).startShowCase(keys)` — matches v5 API
- GoRouter typed routes `const MyRoute().go(context)` — matches 17.x

---

*Generated by 5-agent parallel audit: flutter-auditor, drift-hunter, online-verifier (tavily/pub.dev), junior-dev, staff-engineer. Cross-checked findings; deduplicated. Total findings: 7 blockers, 7 architectural, 11 online drift, 12 cross-doc drift, 10 clarity, 5 scope gaps = 52 actionable issues.*
