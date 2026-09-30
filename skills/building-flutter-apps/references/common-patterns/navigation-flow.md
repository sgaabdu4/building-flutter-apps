# Common Patterns — Navigation Flow

## Read first

1. Validate route params at the route boundary.
2. Missing target = nullable provider + fallback UI; never throw from `build()`.
3. Wizard next-step navigation waits for confirmed notifier state.

## Route-Param Safety + Wizard Sequencing

Use nullable by-id providers. The notifier owns the strict order persist → targeted parent sync → confirmed state + holds `ref.keepAlive()` until done → leaving mid-save still syncs the parent; the screen navigates only on that confirmed serial ([UI effects](../state-management/async-mutations.md#ui-effects)). Reordering causes UI flicker (stale parent) or lost writes on dispose.

```dart
// Plain @riverpod: family + keepAlive would cache every id forever.
@riverpod
Program? programById(Ref ref, String id) {
  final state = ref.watch(programsProvider);
  for (final p in state.items) {
    if (p.id.value == id) return p;
  }
  return null;
}

@riverpod
class ProgramWizardNotifier extends _$ProgramWizardNotifier {
  @override
  ProgramWizardState build(String programId) => const ProgramWizardState();

  Future<void> saveAndAdvance() async {
    final program = ref.read(programByIdProvider(programId));
    if (program == null) return;
    final updated = program.copyWith(/* ...edits... */);
    final link = ref.keepAlive();
    try {
      await ref.read(programRepositoryProvider).save(updated);
      if (!ref.mounted) return;
      ref.read(programsProvider.notifier).upsertProgram(updated);
      state = state.copyWith(successSerial: state.successSerial + 1);
    } catch (error, stackTrace) {
      if (!ref.mounted) return;
      state = state.copyWith(error: AppErrorMapper.from(error));
      Crash.error(error, stackTrace, reason: 'saveAndAdvance');
    } finally {
      link.close();
    }
  }
}

class ProgramStepScreen extends ConsumerWidget {
  const ProgramStepScreen({required this.programId, super.key});

  final String programId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(
      programWizardProvider(programId).select((s) => s.successSerial),
      (previous, next) {
        if (previous != next) const NextRoute().go(context);
      },
    );
    final name = ref.watch(programByIdProvider(programId).select((p) => p?.name));
    // Missing target: placeholder or disabled CTA; never throw from build().
    if (name == null) return const ProgramMissingView();
    return ProgramStepForm(
      name: name,
      onNext: () => unawaited(ref.read(programWizardProvider(programId).notifier).saveAndAdvance()),
    );
  }
}
```
