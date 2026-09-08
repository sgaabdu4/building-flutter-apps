#!/usr/bin/env python3
"""Solve and build the documented Flutter generator compatibility family."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOSTED_PLUGIN_BLOCK = (
    'plugins:\n'
    '  riverpod_lint: ^3.1.9\n'
    '  flutter_skill_lints: ^0.10.0\n'
)
HOSTED_PLUGINS = {
    'riverpod_lint': '^3.1.9',
    'flutter_skill_lints': '^0.10.0',
}


PUBSPEC = """\
name: generator_compatibility_fixture
publish_to: none
environment:
  sdk: '>=3.13.0 <4.0.0'
  flutter: '>=3.47.0'
dependencies:
  flutter:
    sdk: flutter
  flutter_driver:
    sdk: flutter
  flutter_riverpod: 3.4.3
  freezed_annotation: 3.1.0
  go_router: ^18.0.1
  hive_ce: ^2.19.3
  hive_ce_flutter: ^2.3.4
  json_annotation: ^4.12.0
  riverpod_annotation: 4.0.7
dev_dependencies:
  analyzer: 14.3.0
  build_runner: 2.16.1
  flutter_lints: 6.0.0
  freezed: 4.0.1
  go_router_builder: 4.5.0
  hive_ce_generator: 1.11.3
  json_serializable: 6.14.1
  riverpod_generator: 4.0.9
  flutter_test:
    sdk: flutter
"""


BUILD_YAML = """\
targets:
  $default:
    builders:
      json_serializable:
        options:
          explicit_to_json: true
"""


MODEL = """\
import 'package:freezed_annotation/freezed_annotation.dart';

part 'fixture_model.freezed.dart';
part 'fixture_model.g.dart';

@freezed
sealed class FixtureModel with _$FixtureModel {
  const factory FixtureModel({required String name}) = _FixtureModel;

  factory FixtureModel.fromJson(Map<String, dynamic> json) =>
      _$FixtureModelFromJson(json);
}
"""


PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'fixture_provider.g.dart';

@riverpod
String fixtureValue(Ref ref) => 'ok';
"""


HIVE = """\
import 'package:generator_compatibility_fixture/fixture_model.dart';
import 'package:hive_ce_flutter/hive_ce_flutter.dart';

part 'hive_adapters.g.dart';

@GenerateAdapters([
  AdapterSpec<FixtureModel>(),
], firstTypeId: 1)
void registerFixtureAdapters() {}
"""


ROUTER = """\
import 'package:flutter/material.dart';
import 'package:generator_compatibility_fixture/fixture_strings.dart';
import 'package:go_router/go_router.dart';

part 'fixture_route.g.dart';

@TypedGoRoute<FixtureRoute>(path: '/')
class FixtureRoute extends GoRouteData with $FixtureRoute {
  const FixtureRoute();

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      const Scaffold(body: Text(FixtureStrings.title));
}
"""


MAIN = """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:generator_compatibility_fixture/crash.dart';
import 'package:generator_compatibility_fixture/fixture_strings.dart';

Future<void> main() async {
  await Crash.init();
  runFixture();
}

void runFixture() {
  runApp(
    const ProviderScope(
      child: MaterialApp(home: Scaffold(body: Text(FixtureStrings.title))),
    ),
  );
}
"""


CRASH = """\
abstract final class Crash {
  static Future<void> init() async {}
}
"""


FIXTURE_STRINGS = """\
abstract final class FixtureStrings {
  static const String title = 'fixture';
}
"""


MAIN_DEV = """\
import 'package:flutter_driver/driver_extension.dart';
import 'package:generator_compatibility_fixture/main.dart' as app;

void main() {
  runFixtureDev();
}

void runFixtureDev() {
  enableFlutterDriverExtension();
  app.runFixture();
}
"""


WEB_INDEX = """\
<!doctype html>
<html>
  <head>
    <base href="$FLUTTER_BASE_HREF">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Generator fixture</title>
  </head>
  <body>
    <script src="flutter_bootstrap.js" async></script>
  </body>
</html>
"""


TEST = """\
import 'dart:ui' show VoidCallback;

import 'package:flutter_test/flutter_test.dart';
import 'package:generator_compatibility_fixture/fixture_model.dart';
import 'package:generator_compatibility_fixture/fixture_provider.dart';
import 'package:generator_compatibility_fixture/fixture_route.dart';
import 'package:generator_compatibility_fixture/hive_adapters.dart';
import 'package:generator_compatibility_fixture/main.dart' as fixture_app;
import 'package:generator_compatibility_fixture/main_dev.dart' as fixture_dev;

void main() {
  test('generated families compile together', () {
    expect(FixtureModel.fromJson({'name': 'ok'}).name, equals('ok'));
    expect(fixtureValueProvider.toString(), isNotEmpty);
    expect(const FixtureRoute(), isA<FixtureRoute>());
    expect(registerFixtureAdapters, isA<VoidCallback>());
    expect(fixture_app.runFixture, isA<VoidCallback>());
    expect(fixture_dev.runFixtureDev, isA<VoidCallback>());
  });
}
"""


PLUGIN_PROBE = """\
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final probeProvider = Provider<int>((ref) => 0);

void main() {
  final String? title = null;
  runApp(Text(title!, textDirection: TextDirection.ltr));
}
"""


def run(command: list[str], cwd: Path, required_output: tuple[str, ...] = ()) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    output = result.stdout + result.stderr
    if result.returncode:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    missing = [marker for marker in required_output if marker not in output]
    if missing:
        raise SystemExit(
            f"command completed without expected evidence ({' '.join(command)}): {missing}"
        )
    return output


def hosted_plugin_entries(options: str) -> dict[str, str]:
    lines = options.splitlines()
    headers = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r'plugins:[ \t]*', line)
    ]
    if len(headers) != 1:
        raise SystemExit('fixture must contain exactly one top-level plugins map')
    if any(re.fullmatch(r'[ \t]+plugins:[ \t]*', line) for line in lines):
        raise SystemExit('fixture must not use a nested analyzer-plugin map')

    entries: dict[str, str] = {}
    for line in lines[headers[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')):
            break
        entry = re.fullmatch(
            r'  (?P<name>[A-Za-z_][A-Za-z0-9_-]*): (?P<value>\S.*?)\s*', line
        )
        if entry is None:
            raise SystemExit(
                'fixture analyzer-plugin configuration contains an invalid or local entry'
            )
        name = entry['name']
        if name in entries:
            raise SystemExit('fixture analyzer-plugin configuration repeats a plugin')
        entries[name] = entry['value'].strip()
    return entries


def assert_hosted_plugin_configuration(options: str) -> None:
    if hosted_plugin_entries(options) != HOSTED_PLUGINS:
        raise SystemExit('fixture did not retain the exact hosted analyzer-plugin configuration')


def hosted_analysis_options() -> str:
    template = (
        REPO_ROOT / 'skills/building-flutter-apps/references/analysis_options.yaml'
    ).read_text()
    assert_hosted_plugin_configuration(template)
    return template


def assert_hosted_plugin_configuration_regressions() -> None:
    assert_hosted_plugin_configuration(
        HOSTED_PLUGIN_BLOCK + '\nanalyzer:\n  exclude:\n    - build/**\n'
    )
    invalid_configurations = {
        'duplicate top-level plugin maps': HOSTED_PLUGIN_BLOCK + '\n' + HOSTED_PLUGIN_BLOCK,
        'nested plugin map': 'analyzer:\n  '
        + HOSTED_PLUGIN_BLOCK.replace('\n', '\n  '),
        'local plugin map': (
            'plugins:\n'
            '  riverpod_lint: ^3.1.9\n'
            '  flutter_skill_lints:\n'
            '    path: ../flutter_skill_lints\n'
        ),
    }
    for description, options in invalid_configurations.items():
        try:
            assert_hosted_plugin_configuration(options)
        except SystemExit:
            continue
        raise SystemExit(f'fixture validator accepted {description}')


def assert_valid_fixture(package: Path) -> None:
    assert_hosted_plugin_configuration(
        (package / 'analysis_options.yaml').read_text()
    )
    if (package / 'pubspec_overrides.yaml').exists():
        raise SystemExit('valid fixture must not contain pubspec_overrides.yaml')
    lock = package / 'pubspec.lock'
    if not lock.exists():
        raise SystemExit('pub get did not create pubspec.lock')
    lock_text = lock.read_text()
    if 'source: path' in lock_text or 'dependency_overrides' in lock_text:
        raise SystemExit('valid fixture resolved through an override or path dependency')
    analyzer_version = re.search(
        r'(?ms)^  analyzer:\n.*?^    version: "([^"]+)"', lock_text
    )
    if analyzer_version is None or analyzer_version.group(1) != '14.3.0':
        actual = analyzer_version.group(1) if analyzer_version else 'missing'
        raise SystemExit(f'expected analyzer 14.3.0, resolved {actual}')
    resolved = json.loads((package / '.dart_tool' / 'package_config.json').read_text())
    names = {entry['name'] for entry in resolved['packages']}
    required = {
        'riverpod_generator',
        'freezed',
        'hive_ce_generator',
        'json_serializable',
        'go_router_builder',
    }
    missing = required - names
    if missing:
        raise SystemExit(f'generated packages missing from package_config.json: {sorted(missing)}')
    generated = [
        package / 'lib/fixture_model.freezed.dart',
        package / 'lib/fixture_model.g.dart',
        package / 'lib/fixture_provider.g.dart',
        package / 'lib/hive_adapters.g.dart',
        package / 'lib/fixture_route.g.dart',
    ]
    absent = [str(path.relative_to(package)) for path in generated if not path.exists()]
    if absent:
        raise SystemExit(f'expected generated outputs missing: {absent}')
    required_output_tokens = {
        'fixture_model.freezed.dart': 'FixtureModel',
        'fixture_model.g.dart': 'FixtureModelFromJson',
        'fixture_provider.g.dart': 'fixtureValueProvider',
        'hive_adapters.g.dart': 'FixtureModelAdapter',
        'fixture_route.g.dart': 'FixtureRoute',
    }
    for name, token in required_output_tokens.items():
        text = (package / 'lib' / name).read_text()
        if token not in text:
            raise SystemExit(f'generated output {name} lacks expected symbol evidence')


def assert_plugin_diagnostics(package: Path) -> None:
    result = subprocess.run(
        ['dart', 'analyze'], cwd=package, text=True, capture_output=True
    )
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise SystemExit('plugin probe unexpectedly passed analysis')
    missing = [
        code
        for code in ('avoid_null_bang', 'missing_provider_scope')
        if code not in output
    ]
    if missing:
        raise SystemExit(f'plugin probe did not report expected diagnostics: {missing}')
    if 'server.pluginError' in output:
        raise SystemExit('plugin probe reported server.pluginError')


def assert_web_build(package: Path) -> None:
    required = [
        package / 'build/web/index.html',
        package / 'build/web/flutter_bootstrap.js',
    ]
    absent = [str(path.relative_to(package)) for path in required if not path.exists()]
    if absent:
        raise SystemExit(f'web build output missing: {absent}')


def main() -> None:
    assert_hosted_plugin_configuration_regressions()
    with tempfile.TemporaryDirectory(prefix='flutter-skill-generator-') as directory:
        package = Path(directory)
        (package / 'lib').mkdir()
        (package / 'test').mkdir()
        (package / 'web').mkdir()
        (package / 'pubspec.yaml').write_text(PUBSPEC)
        (package / 'analysis_options.yaml').write_text(hosted_analysis_options())
        (package / 'build.yaml').write_text(BUILD_YAML)
        (package / 'lib/fixture_model.dart').write_text(MODEL)
        (package / 'lib/fixture_provider.dart').write_text(PROVIDER)
        (package / 'lib/hive_adapters.dart').write_text(HIVE)
        (package / 'lib/fixture_route.dart').write_text(ROUTER)
        (package / 'lib/main.dart').write_text(MAIN)
        (package / 'lib/crash.dart').write_text(CRASH)
        (package / 'lib/fixture_strings.dart').write_text(FIXTURE_STRINGS)
        (package / 'lib/main_dev.dart').write_text(MAIN_DEV)
        (package / 'web/index.html').write_text(WEB_INDEX)
        (package / 'test/fixture_test.dart').write_text(TEST)

        run(['flutter', 'pub', 'get'], package)
        run(['dart', 'run', 'build_runner', 'build'], package)
        assert_valid_fixture(package)
        (package / 'lib/plugin_probe.dart').write_text(PLUGIN_PROBE)
        assert_plugin_diagnostics(package)
        (package / 'lib/plugin_probe.dart').unlink()
        run(['dart', 'analyze'], package, required_output=('No issues found!',))
        run(['flutter', 'test'], package, required_output=('All tests passed!',))
        run(['flutter', 'build', 'web', '--no-pub'], package)
        assert_web_build(package)

    print('HOSTED_LINT_RESOLUTION_OK flutter_skill_lints=^0.10.0')
    print('COMPATIBILITY_FIXTURE_OK')


if __name__ == '__main__':
    main()
