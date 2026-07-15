# Presentation Widget Boundary

## Read first

- Reusable widget = immutable view inputs + typed callback outputs.
- Navigation/workflow/domain/infrastructure owner = screen + typed route + generated notifier/provider.

## Ownership

| Owner | Contract |
|---|---|
| `presentation/widgets/` | Render immutable view inputs + emit typed callbacks + own UI lifecycle objects only. |
| `presentation/screens/` | Bind providers + map domain state to view data + branch visible workflow + coordinate callbacks. |
| Typed route | Own page navigation + route arguments + route results. |
| Generated notifier/provider | Own domain selection + workflow/mutation state + repository/service calls. |

Widget `State` allowed = text/scroll/page/tab/animation controllers + focus nodes + cancellable UI timers/debouncers.

Widget `State` forbidden = domain entities + selected records + page/navigation stacks + workflow flags + provider-derived caches/snapshots/maps.

Widget dependencies forbidden = GoRouter + page-route `Navigator.push*` + repositories + datasources + services + persistence/backend/HTTP SDKs + provider reads/mutations.

Local modal dismissal allowed = `Navigator.pop(result)` with no work after pop; caller owns subsequent mutation/page navigation.

Lints: `presentation_widget_navigation_forbidden`, `presentation_widget_controller_state`, `presentation_widget_infrastructure_dependency`.

## WRONG

```dart
class _ContentViewState extends State<ContentView> {
  final List<Entity> _pageStack = [];
  Entity? _selected;

  Future<void> _open(Entity item) async {
    if (item.children.isNotEmpty) {
      setState(() => _pageStack.add(item));
    } else {
      setState(() => _selected = item);
      await ref.read(contentRepositoryProvider).load(item.id);
    }
  }

  void _back() {
    if (_pageStack.isEmpty) context.pop();
  }
}
```

## DO

```dart
final class ContentView extends StatelessWidget {
  const ContentView({
    required this.items,
    required this.onItemTap,
    required this.onBack,
    super.key,
  });

  final UnmodifiableListView<ContentItemViewData> items;
  final ValueChanged<ContentItemViewData> onItemTap;
  final VoidCallback onBack;

  // build = render items + invoke callbacks only
}
```

Screen callback → choose child-list/article view + call typed route.

Notifier action → select domain record + call repository/service + expose workflow state.
