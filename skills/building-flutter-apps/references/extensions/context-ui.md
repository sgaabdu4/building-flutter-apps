# Extensions — Context And UI

## Read first

1. BuildContext operations live in `core/extensions/build_context_extensions.dart` or `context_extensions.dart`.
2. Route-current checks use `context.isCurrentModalRoute`; never inline `ModalRoute` current-route APIs at call sites.
3. Snackbars/dialog helpers are UI boundary utilities; notifiers emit state, widgets listen and dispatch UI effects.

## Trigger

Signals: `BuildContext`, `ModalRoute`, `SnackBarUtils`, dialog helpers, route-current guards, snackbar from notifier.
Before code: output `Reading: context-ui.md`.

## Context extensions

Expose semantic helpers from `core/extensions/extensions.dart`:

```dart
extension BuildContextX on BuildContext {
  AppLocalizations get l10n => AppLocalizations.of(this);
  TextTheme get textTheme => Theme.of(this).textTheme;
  bool get isCurrentModalRoute => ModalRoute.of(this)?.isCurrent ?? false;
}
```

Forbidden outside the extension owner:

```dart
ModalRoute.of(context)?.isCurrent;
ModalRoute.isCurrentOf(context);
```

Lint: `use_context_is_current_modal_route`.

## Dialog helpers

Put repeated modal launch details in semantic helpers. Always pass `routeSettings` so observers/analytics can see modals.

```dart
Future<T?> showAppSheet<T>({
  required BuildContext context,
  required String routeName,
  required WidgetBuilder builder,
}) {
  return showModalBottomSheet<T>(
    context: context,
    routeSettings: RouteSettings(name: routeName),
    builder: builder,
  );
}
```

Lint: `modal_helper_requires_route_settings`.

## Snackbar dispatch

Notifier owns durable status fields; widget listens and calls UI helpers.

```dart
ref.listen(
  profileNotifierProvider.select((state) => state.errorSerial),
  (previous, next) {
    if (previous != next && context.mounted) {
      showProfileSaveFailedSnackBar(context, context.l10n);
    }
  },
);
```

The UI helper may wrap `SnackBarUtils`. Do not call `SnackBarUtils.show...` from notifiers, repositories, or datasources.

## Full reference

For examples of every extension owner, read [extensions-utilities.md](../extensions-utilities.md).
