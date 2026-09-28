# Extensions — Context And UI

## Read first

1. BuildContext operations live in `core/extensions/context_extensions.dart`, exported from `core/extensions/extensions.dart`.
2. Route-current checks use `context.isCurrentModalRoute`; never inline `ModalRoute` current-route APIs at call sites.
3. Snackbars/dialog helpers are UI boundary utilities; notifiers emit state, widgets listen and dispatch UI effects.

## Trigger

Signals: `BuildContext`, `ModalRoute`, `SnackBarUtils`, dialog helpers, route-current guards, snackbar from notifier.

## Context extensions

Expose semantic helpers from `core/extensions/extensions.dart`:

```dart
// core/extensions/context_extensions.dart
extension BuildContextX on BuildContext {
  AppLocalizations get l10n => .of(this);
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

Put repeated modal launch details in semantic `BuildContext` extension members, never top-level functions in widget files. Always pass `routeSettings` so observers/analytics can see modals.

```dart
// core/extensions/context_extensions.dart
extension ModalContextX on BuildContext {
  Future<T?> showAppSheet<T>({
    required String routeName,
    required WidgetBuilder builder,
  }) {
    return showModalBottomSheet<T>(
      context: this,
      routeSettings: RouteSettings(name: routeName),
      builder: builder,
    );
  }
}
```

Lint: `modal_helper_requires_route_settings`.

## Snackbar dispatch

Notifier owns durable status fields; widget listens and calls UI helpers.

```dart
ref.listen(
  profileProvider.select((state) => state.errorSerial),
  (previous, next) {
    if (previous != next && context.mounted) {
      showProfileSaveFailedSnackBar(context, context.l10n);
    }
  },
);
```

The UI helper may wrap `SnackBarUtils`. Do not call `SnackBarUtils.show...` from notifiers, repositories, or datasources.
