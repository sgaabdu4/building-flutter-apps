# V6 Violation Fixture

```dart
final result = await ref.read(mutationProvider.notifier).run(Mutation<Order>(
  request: createOrder,
));
```
