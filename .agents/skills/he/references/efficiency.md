# Bulk + async + performance

Apply only to the changed flow. Derive limits from its actual service/behavior contract; unknown limits remain unverified.

| Flow | Implementation + meaningful assertion |
| --- | --- |
| Batches | Reuse native batching/pagination/streams. Exercise empty, boundary + final partial inputs; assert exact records/order, no loss/duplication + expected calls. Account for payload limits and retries, not only item count. |
| Fan-out / queue | Bound active + pending work; define overload behavior. Hold workers at a controlled boundary, prove both bounds, then release and verify completion, errors + relevant cancellation/timeout cleanup. A semaphore around eagerly created tasks does not bound pending memory. |
| Repeated I/O | Assert required query/request counts across representative input sizes, cache states + partial failures. Retries must not duplicate effects or amplify overload. |
| Scaling | Name input dimensions + expected time/space growth; inspect repeated scans, copies, sorts + I/O. Assert independently justified operation bounds where feasible; include skewed inputs when relevant. |

Use controlled inputs, fake clocks or synchronization instead of sleep-based comparisons. Native pattern lints and timing samples do not prove general Big-O.

Async does not make CPU work parallel; unbounded gathers can worsen resource use.

## Optimisation

Only when the requested outcome is a measured improvement (time, memory, size, cost):

1. Reproduce the real workload. The plan names the metric, target, measurement command and correctness constraints.
2. Show the measurement detects a known change, then freeze the workload, command and configuration for the comparison.
3. Record revision, configuration and repeated samples on both sides, enough that the difference exceeds run-to-run spread. Never run competing measurements on the same constrained CPU, disk or network.
4. One hypothesis per change: measure before and after, run the existing gates, and keep only demonstrated improvements or equally fast simplifications. Revert rejected task-owned changes only.
5. Record baseline, samples and decisions in the plan's Baseline/Verification. Stop at the authorised target or budget, or when further work is unjustified; never weaken a check or shrink the workload to meet a target.

Diagnose surprises with [troubleshooting](../../research/references/troubleshooting.md); prove affected journeys per [testing](testing.md).
