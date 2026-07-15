# Common Patterns — Modals and Navigation


## Read first

1. Modal renders immutable snapshot + returns a typed result.
2. Screen/notifier owns mutation, teardown, and page navigation.
3. Dismiss the active modal navigator before typed-route navigation.

## Modal Snapshot Pattern

**Rule.** Screen computes immutable `<Feature>Summary` via `ref.read`. Dialog renders the snapshot and returns a typed result. Screen dispatches the notifier mutation after dismissal. Dialog has no provider reads. Notifier owns success teardown and preserves failure state.

```dart
// NEVER — dialog hosts mutation + watches mutable record
class ConfirmDialog extends ConsumerWidget {
  const ConfirmDialog({required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entity = ref.watch(entityProvider(id));                      // re-evaluates mid-dismiss
    final (:isSaving, :itemsByCategoryId) = ref.watch(                 // record with Map getter → rebuild storm
      formProvider.select((s) => (isSaving: s.isSaving, itemsByCategoryId: s.itemsByCategoryId)),
    );
    return AppPrimaryButton(
      onPressed: () async {
        final ok = await ref.read(formProvider.notifier).save(entity); // mutates state.items
        if (!context.mounted) return;
        Navigator.of(context, rootNavigator: true).pop();              // pop AFTER mutation
        if (ok) context.pop();                                         // triggers PopScope flash
      },
      label: itemsByCategoryId.isEmpty ? 'Exit' : 'Confirm',
    );
  }
}
```

```dart
// DO — value object + caller orchestrates
class ConfirmSummary {
  const ConfirmSummary({required this.entity, required this.confirmed});
  final Entity entity;
  final bool confirmed;

  static ConfirmSummary? compute({required Entity? entity, required FormState state}) {
    if (entity == null) return null;
    return ConfirmSummary(entity: entity, confirmed: state.items.isNotEmpty);
  }
}

class ConfirmScreenBoundary extends ConsumerWidget {
  const ConfirmScreenBoundary({required this.id, super.key});
  final String id;

  Future<void> _onPressed(BuildContext context, WidgetRef ref) async {
    final summary = ConfirmSummary.compute(
      entity: ref.read(entityProvider(id)),
      state: ref.read(formProvider),
    );
    if (summary == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      routeSettings: const RouteSettings(name: 'confirm-dialog'),
      builder: (_) => ConfirmDialog(summary: summary),
    );
    if (confirmed != true || !context.mounted) return;
    await ref.read(formProvider.notifier).save(summary.entity);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      AppTextButton(onPressed: () => _onPressed(context, ref), label: 'Confirm');
}

class ConfirmDialog extends StatelessWidget {
  const ConfirmDialog({required this.summary, super.key});
  final ConfirmSummary summary;

  @override
  Widget build(BuildContext context) => AppPrimaryButton(
      onPressed: () => Navigator.of(context).pop(true),
      label: summary.confirmed ? 'Confirm' : 'Exit',
    );
}
```

**Test.** Pump dialog with synthetic `ConfirmSummary`; don't drive rendering from provider state.

```dart
testWidgets('confirm dialog renders from summary', (tester) async {
  await tester.pumpWidget(
    MaterialApp(
      home: ConfirmDialog(
        summary: const ConfirmSummary(entity: e, confirmed: true),
      ),
    ),
  );
  expect(find.text('Confirm'), findsOneWidget);
});
```

Lints: `dialog_widget_subscribes_to_mutable_provider`, `modal_high_frequency_watch_not_leaf`, `dialog_button_pop_then_state_mutation`, `select_returns_unstable_record_identity`, `build_method_assigns_to_field`, `build_calls_mutating_instance_method`, `widget_calls_notifier_teardown_after_await`, `popscope_bypass_uses_go_not_pop`, `modal_helper_requires_route_settings`.

See also: [State Teardown Belongs in the Notifier](../state-management-lifecycle.md#state-teardown-belongs-in-the-notifier), [Dismiss Modal → Push Route](#dismiss-modal-push-route-bottom-sheet-navigation).

## Dismiss Modal → Push Route (Bottom Sheet Navigation)

**Rule.** Pop sheet with result; caller awaits result, then pushes route.

**NEVER:**
```dart
Navigator.of(context).pop();
await const CreateExerciseRoute().push<String>(context);
```

**DO — await pop future, then navigate:**
```dart
// Sheet widget:
Future<void> _onCreateTapped(BuildContext context) async {
  Navigator.of(context).pop(CreateChoice.exercise);
}

// Caller that opened the sheet:
Future<void> openCreateSheet(BuildContext context) async {
  final choice = await context.showScrollableBottomSheet<CreateChoice>(
    builder: (_) => const CreateSheet(),
  );
  if (!context.mounted || choice != CreateChoice.exercise) return;
  await const CreateExerciseRoute().push<String>(context);
}
```

## Pop Fallback Helpers Check Navigator Stacks

Check root + local Navigator stacks before typed fallback.

```dart
extension GoRouterPopX on BuildContext {
  bool popIfCan<T extends Object?>([T? result]) {
    if (!this.mounted) return false;
    final rootNavigator = Navigator.maybeOf(this, rootNavigator: true);
    if (rootNavigator != null && rootNavigator.canPop()) {
      rootNavigator.pop<T>(result);
      return true;
    }

    final navigator = Navigator.maybeOf(this);
    if (navigator != null && navigator.canPop()) {
      navigator.pop<T>(result);
      return true;
    }

    if (!canPop()) return false;
    pop<T>(result);
    return true;
  }

  void popOrGo<T extends Object?>(GoRouteData fallbackRoute, [T? result]) {
    if (popIfCan<T>(result)) return;
    fallbackRoute.go(this);
  }
}
```

Use `popOrGo` on screens opened by either `push` or direct deep link. Fallback must be a typed `GoRouteData`.

Lint: `pop_fallback_helper_must_check_navigator_stack` enforces mounted + root/local Navigator checks; `router_context_navigation_extension` allows typed fallback helpers only when they call `popIfCan` first.
