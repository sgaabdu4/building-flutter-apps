# Localization

## Trigger

Signals: gen-l10n, ARB, AppLocalizations, plural, select, l10n.yaml
Before generating code in this area, output verbatim: `Reading: localization.md`


## Rules

1. **MUST** use Flutter gen-l10n for user-visible copy in production UI.
2. **MUST** add every user-facing key to the template ARB first, then update supported locales.
3. **MUST** include descriptions for ARB keys that are not obvious.
4. **MUST** use placeholders for runtime values. Do not concatenate localized strings.
5. **MUST** use plural/select syntax for counts, gender, roles, or status choices.
6. **MUST NOT** use `AppLocalizations.of(context)!`. Prefer `nullable-getter: false`; if an existing project uses nullable getters, handle null once in a context extension.
7. **MUST NOT** store localized copy in domain entities, repositories, datasources, or notifiers. Store semantic state there; render copy in UI.

## Setup

Add dependencies:

```bash
flutter pub add flutter_localizations --sdk=flutter
flutter pub add intl:any
```

Enable generation:

```yaml
flutter:
  generate: true
```

Create `l10n.yaml`:

```yaml
arb-dir: lib/l10n
template-arb-file: app_en.arb
output-localization-file: app_localizations.dart
synthetic-package: false
nullable-getter: false
use-escaping: true
```

## App Wiring

```dart
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:my_app/l10n/app_localizations.dart';

class AppRoot extends StatelessWidget {
  const AppRoot({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      routerConfig: appRouter,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
    );
  }
}
```

Add a single extension:

```dart
import 'package:flutter/widgets.dart';
import 'package:my_app/l10n/app_localizations.dart';

extension LocalizationContext on BuildContext {
  AppLocalizations get l10n => AppLocalizations.of(this);
}
```

Use it in widgets:

```dart
class ProductEmptyState extends StatelessWidget {
  const ProductEmptyState({super.key});

  @override
  Widget build(BuildContext context) {
    return Text(context.l10n.productsEmptyTitle);
  }
}
```

## ARB Patterns

Base template:

```json
{
  "productsEmptyTitle": "No products yet",
  "@productsEmptyTitle": {
    "description": "Empty-state title on the product list screen"
  }
}
```

Placeholder:

```json
{
  "welcomeUser": "Welcome, {name}",
  "@welcomeUser": {
    "description": "Greeting shown after sign in",
    "placeholders": {
      "name": {
        "type": "String",
        "example": "Amira"
      }
    }
  }
}
```

Plural:

```json
{
  "cartItemCount": "{count, plural, =0{No items} =1{1 item} other{{count} items}}",
  "@cartItemCount": {
    "description": "Number of items in the cart",
    "placeholders": {
      "count": {
        "type": "num",
        "format": "compact"
      }
    }
  }
}
```

Select:

```json
{
  "inviteStatus": "{status, select, pending{Pending} accepted{Accepted} declined{Declined} other{Unknown}}",
  "@inviteStatus": {
    "description": "Invite status label",
    "placeholders": {
      "status": {
        "type": "String"
      }
    }
  }
}
```

## Notifier Boundary

Notifiers should expose semantic state, not translated copy.

```dart
@freezed
sealed class InviteState with _$InviteState {
  const factory InviteState({
    required InviteStatus status,
  }) = _InviteState;
}

class InviteStatusLabel extends StatelessWidget {
  const InviteStatusLabel({super.key, required this.status});

  final InviteStatus status;

  @override
  Widget build(BuildContext context) {
    return switch (status) {
      InviteStatus.pending => Text(context.l10n.invitePending),
      InviteStatus.accepted => Text(context.l10n.inviteAccepted),
      InviteStatus.declined => Text(context.l10n.inviteDeclined),
    };
  }
}
```

## Testing

- Widget tests should wrap widgets in the app localization delegates.
- Snapshot/preview data should include longest expected localized copy.
- Router/deep-link tests should not assert localized text unless the route is
  locale-specific.

## Checklist

- [ ] `l10n.yaml` exists and gen-l10n is enabled.
- [ ] `AppLocalizations` is wired at `MaterialApp`/`CupertinoApp`.
- [ ] User-facing strings are in ARB files.
- [ ] Placeholders/plurals/selects are used instead of string concatenation.
- [ ] Notifiers expose semantic state, not translated copy.
- [ ] Widget tests/previews include localization delegates or app preview shell.

## Recap

1. MUST use Flutter gen-l10n for all user-visible copy in production UI — NEVER ad hoc string constants for user-facing text.
2. MUST NOT call `AppLocalizations.of(context)!` directly — configure `nullable-getter: false` in `l10n.yaml` or use a context extension to avoid null-assertion boilerplate.
3. MUST NOT store localized copy in domain entities, repositories, datasources, or notifiers — expose semantic state and let the UI layer render translated copy.

