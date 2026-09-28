# Domain-driven design

Apply when business meaning or rules determine the structure. Start with actual use cases, terminology + counterexamples from domain knowledge; unfamiliar vocabulary stays an open question, not an invented model.

| Decision | Design test |
| --- | --- |
| Shared language | Do domain experts, code and tests use the same term for the same concept within this context? |
| Bounded context | Where do meaning, rules or ownership change? Keep each model coherent; map actual context relationships + translation points with Mermaid when boundaries are involved. A context is not automatically a service or database. |
| Entity / value | Does identity persist through change, or does equality depend on attributes? Model the former as identity-bearing; prefer immutable values for the latter when supported by the domain. |
| Aggregate | Which invariants must hold atomically? Choose the smallest consistency boundary that protects them; route changes through its owner and test concurrent/conflicting operations. Do not group an entire object graph merely because tables relate. |
| Cross-context contract | Define exchanged meaning, ownership, permitted consistency delay + failure/retry behavior. Translate differing models instead of forcing one universal entity across contexts. |

- Put business policy at its domain owner; keep transport/storage details from dictating the model. Reuse existing seams; a repository interface per entity or a domain-service class per action is not a requirement.
- Simple CRUD can remain simple. DDD alone does not justify microservices, CQRS, event sourcing, an event bus or new layers. Introduce a pattern only for a current domain/consistency need.
- Verify invariants through real use cases, rejected transitions + relevant concurrency/retry failures. A context diagram or renamed class does not prove the rules hold.

Concept references: [Bounded contexts](https://martinfowler.com/bliki/BoundedContext.html) · [Aggregates](https://martinfowler.com/bliki/DDD_Aggregate.html).
