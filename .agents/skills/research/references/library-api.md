# Library, API and platform contracts

- Identify installed and target versions from manifests, lockfiles and runtime evidence as needed; include endpoint, operating mode and relevant configuration.
- Inspect matching official docs, source and changelogs for the operation in question. Documentation retrieval tools may help locate sources but do not replace checking their version and applicability.
- Check the material contract: accepted inputs, returned values, errors, state changes and configuration. Include authentication, ordering, retries or idempotency only where the operation depends on them.
- Inspect how the repository calls the API and consumes its result. Local types, mocks and old examples can disagree with the current service contract.
- When changing versions or selecting a remedy, inspect the relevant migration notes and known issues. A newer version is not evidence that a particular problem is fixed.
- If local compatibility determines the recommendation, use an authorized minimal parser/compiler/runtime probe. Keep documented support distinct from observed integration behavior.
- If exact-version documentation is unavailable, use relevant source or clearly label the closest evidence and the unresolved compatibility question.
