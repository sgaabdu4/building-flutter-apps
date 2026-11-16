# Localization

## Read first

1. All user-visible production copy uses gen-l10n ARB, never ad hoc UI strings.
2. Add keys to template ARB first; include descriptions, placeholders, plural/select where needed.
3. Widgets bind `final l10n = context.l10n;`; no `AppLocalizations.of(context)!` or chained `context.l10n.key`.
4. Domain/repos/datasources/notifiers expose semantic state, not localized copy.
5. Configure ARB/generated paths explicitly; import generated `app_localizations.dart` from that path.

## Trigger

Signals: gen-l10n, ARB, AppLocalizations, plural, select, l10n.yaml

## Rules

1. **MUST** use Flutter gen-l10n for user-visible copy in production UI.
2. **MUST** add every user-facing key to the template ARB first, then update supported locales.
3. **MUST** include descriptions for ARB keys that are not obvious.
4. **MUST** use placeholders for runtime values. Do not concatenate localized strings.
5. **MUST** use plural/select syntax for counts, gender, roles, or status choices.
6. **MUST NOT** use `AppLocalizations.of(context)!`. Prefer `nullable-getter: false`; if an existing project uses nullable getters, handle null once in a context extension.
7. **MUST NOT** store localized copy in domain entities, repositories, datasources, or notifiers. Store semantic state there; render copy in UI.
8. **Configure gen-l10n paths explicitly.** Put ARB files in `arb-dir` (`lib/l10n` by default). Generated Dart is written to `${arb-dir}/${output-localization-file}` unless `output-dir` is set, then it is written to `${output-dir}/${output-localization-file}`.

## Setup

Add dependencies:

```bash
flutter pub add flutter_localizations --sdk=flutter
flutter pub add intl
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
nullable-getter: false
use-escaping: true
```

With the config above, generated output is `lib/l10n/app_localizations.dart`; import:

```dart
import 'package:my_app/l10n/app_localizations.dart';
```

Generated output and `--fatal-infos`: on Flutter 3.50 and later `flutter
gen-l10n` writes `GlobalMaterialLocalizations` and `GlobalCupertinoLocalizations`
from `flutter_localizations` into the main file `app_localizations.dart`, and the
analyzer reports two `deprecated_member_use` infos there. gen-l10n has no option
that avoids it. The per-language files (`app_localizations_en.dart` and the
others) have no deprecated uses. Keep `dart analyze --fatal-infos` green by
excluding only the main file, by its exact path (`lib/l10n/app_localizations.dart`
by default; a project with `output-dir` or `output-localization-file` in
`l10n.yaml` uses that path):

```yaml
analyzer:
  exclude:
    - "lib/l10n/app_localizations.dart"
```

Do not use a glob such as `**/app_localizations*.dart` and do not add an ignore
comment. In a project with Hard Eng installed the exclusion is accepted only for
that one file and only when it is marked generated, so add this line to
`.gitattributes`:

```text
lib/l10n/app_localizations.dart linguist-generated=true
```

The fixture runs `flutter gen-l10n`, Hard Eng's check of the analyzer
exclusions and `dart analyze --fatal-infos` on 3.47.9 and 3.50.0, and requires
Hard Eng to refuse the old glob.

## App Wiring

```dart
import 'package:material_ui/material_ui.dart';
import 'package:my_app/l10n/app_localizations.dart';

class AppRoot extends StatelessWidget {
  const AppRoot({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      routerConfig: appRouter,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        ...GlobalMaterialLocalizations.delegates,
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
  AppLocalizations get l10n => .of(this);
}
```

Use it in widgets by binding localizations once at the top of `build`:

```dart
class ProductEmptyState extends StatelessWidget {
  const ProductEmptyState({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;

    return Text(l10n.productsEmptyTitle);
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
    final l10n = context.l10n;

    return switch (status) {
      .pending => Text(l10n.invitePending),
      .accepted => Text(l10n.inviteAccepted),
      .declined => Text(l10n.inviteDeclined),
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
- [ ] Generated l10n files are in `arb-dir` or `output-dir`, and imports use that path.
- [ ] `AppLocalizations` is wired at `MaterialApp`/`CupertinoApp`.
- [ ] Widgets bind `final l10n = context.l10n;` before localized key reads.
- [ ] User-facing strings are in ARB files.
- [ ] Placeholders/plurals/selects are used instead of string concatenation.
- [ ] Notifiers expose semantic state, not translated copy.
- [ ] Widget tests/previews include localization delegates or app preview shell.
