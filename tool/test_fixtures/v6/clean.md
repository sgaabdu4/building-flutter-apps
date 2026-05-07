# V6 Clean Fixture — Mutation< usage with experimental disclaimer nearby

<!-- NOTE: Mutation<T> is an experimental Riverpod API subject to change. -->

```dart
final result = await ref.read(mutationProvider.notifier).run(Mutation<Order>(
  request: createOrder,
));
```
