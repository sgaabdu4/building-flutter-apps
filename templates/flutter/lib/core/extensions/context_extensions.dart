import 'package:flutter/widgets.dart';

extension ContextExtensions on BuildContext {
  /// Whether this context's nearest modal route is currently visible.
  bool get isCurrentModalRoute {
    final isCurrent = ModalRoute.isCurrentOf(this);
    if (isCurrent == null) return true;
    return isCurrent;
  }
}
