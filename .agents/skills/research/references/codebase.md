# Codebase investigation

- Establish the canonical repository, relevant revision, working changes and applicable project instructions. Preserve unrelated work.
- Derive the relevant surfaces from the question: entry points, callers, data contracts, integrations, configuration, tests and delivery paths. Do not inspect unrelated surfaces just to fill a checklist.
- Trace actual behavior through its owners and consumers. A filename, symbol match or graph edge is a lead; inspect the code needed to support the conclusion.
- For cross-package or cross-service claims, follow the relevant boundary on both sides. Include generated outputs or their generators when they affect behavior.
- Use configured search/graph tools where helpful; account for index freshness, exclusions and dynamic behavior. Confirm decisive claims against current source or runtime evidence.
- Test negative claims with a bounded search and state the searched scope. An absent search result is not proof that behavior cannot exist elsewhere.
- Separate implementation, test intent and observed runtime behavior. Cite paths and revisions where they matter; identify the smallest missing proof rather than assuming success.
