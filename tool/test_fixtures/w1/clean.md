# W1 Clean Fixture

Public widget — same file, marked test-only:

```dart
@visibleForTesting
class Header extends StatelessWidget {
  const Header({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox();
}
```

State subclass exempt (Flutter convention requires private):

```dart
class MyScreen extends StatefulWidget {
  const MyScreen({super.key});

  @override
  State<MyScreen> createState() => _MyScreenState();
}

class _MyScreenState extends State<MyScreen> {
  @override
  Widget build(BuildContext context) => const SizedBox();
}
```
