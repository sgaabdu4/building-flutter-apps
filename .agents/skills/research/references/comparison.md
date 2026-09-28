# Tool, approach and gap comparisons

- Build the comparison dimensions before judging candidates. Derive them from the user's outcome, current setup and the documented capabilities of named tools; include relevant capabilities the user did not mention.
- Compare candidates against the same material dimensions. For cross-language comparisons, compare what each check detects, not just similar tool or feature names.
- Establish what the current setup actually enables. Separate available, default, opt-in, configured and verified behavior; installing a tool does not enable every feature.
- For a missing capability, check whether an existing tool can provide it before proposing another tool. Assess combined alternatives against the entire capability set they would replace.
- For each material capability, establish scope, configuration, limitations and evidence. Use supported, partial, absent, unknown or not applicable accurately; do not convert unknown to absent.
- When recommending a gate, inspect finding severity, thresholds, exit behavior, scan errors, empty/incomplete scans, exclusions, baseline behavior and supported versions. A report or successful exit alone does not prove enforcement.
- Assess compatibility, execution cost, maintenance and licensing when they could change the choice. Label vendor benchmarks and distinguish them from measurements on the user's workload.
- Search official issue trackers and relevant community discussions for counterexamples and alternatives when reliability matters. User-requested sources such as Reddit must be included; a few posts do not establish community consensus.
- Run a bounded local probe when the decision depends on actual behavior and the task authorizes it. Otherwise state the untested claim and the validation needed; do not present documentation as runtime proof.
- Finish with the recommended set, overlap, remaining gaps and reasons to defer or reject additions. Trace the conclusion back to the original dimensions before saying the set is sufficient.
