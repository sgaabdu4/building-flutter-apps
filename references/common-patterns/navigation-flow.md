# Common Patterns — Navigation Flow

## Route-Param Safety + Wizard Sequencing

Use nullable by-id providers. Keep mutation order strict before navigate.

```dart
// Family + keepAlive caches every key forever — memory leak. Use plain `@riverpod`
// so each per-id provider auto-disposes when no widget watches it.
@riverpod
Program? programById(Ref ref, String id) {
  final state = ref.watch(programsProvider);
  for (final p in state.items) {
    if (p.id == id) return p;
  }
  return null;
}

Future<void> onNext(BuildContext context, WidgetRef ref, String programId) async {
  final program = ref.read(programByIdProvider(programId));
  if (program == null) return; // disable CTA / show placeholder

  // ✅ DO — fixed sequence: persist → targeted sync → navigate.
  //    Reorder = UI flicker (stale parent) OR lost writes on dispose.
  final updatedParent = program.copyWith(/* ...edits... */);
  await ref.read(programRepositoryProvider).save(updatedParent);
  ref.read(programsProvider.notifier).upsertProgram(updatedParent);
  if (!context.mounted) return;
  _goNext(context);
}

void _goNext(BuildContext context) {
  const NextRoute().go(context);
}
```
