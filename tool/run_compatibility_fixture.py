#!/usr/bin/env python3
"""Solve and build the documented Flutter generator compatibility family."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path


PUBSPEC = """\
name: generator_compatibility_fixture
publish_to: none
environment:
  sdk: '>=3.13.0 <4.0.0'
  flutter: '>=3.47.0'
dependencies:
  flutter:
    sdk: flutter
  flutter_riverpod: 3.3.2
  freezed_annotation: 3.1.0
  go_router: ^17.5.0
  hive_ce: ^2.19.3
  hive_ce_flutter: ^2.3.4
  json_annotation: ^4.12.0
  riverpod_annotation: 4.0.3
dev_dependencies:
  build_runner: 2.15.1
  freezed: 3.2.6-dev.1
  go_router_builder: 4.4.0
  hive_ce_generator: 1.11.2
  json_serializable: 6.14.1
  riverpod_generator: 4.0.4
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
import 'package:hive_ce_flutter/hive_ce_flutter.dart';
import 'fixture_model.dart';

part 'hive_adapters.g.dart';

@GenerateAdapters([
  AdapterSpec<FixtureModel>(),
], firstTypeId: 1)
void registerFixtureAdapters() {}
"""


ROUTER = """\
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

part 'fixture_router.g.dart';

@TypedGoRoute<FixtureRoute>(path: '/')
class FixtureRoute extends GoRouteData with $FixtureRoute {
  const FixtureRoute();

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      const Scaffold(body: Text('fixture'));
}
"""


MAIN = """\
import 'package:flutter/material.dart';

void main() {
  runApp(const MaterialApp(home: Scaffold(body: Text('fixture'))));
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
import 'package:flutter_test/flutter_test.dart';
import 'package:generator_compatibility_fixture/fixture_model.dart';
import 'package:generator_compatibility_fixture/fixture_provider.dart';

void main() {
  test('generated families compile together', () {
    expect(FixtureModel.fromJson({'name': 'ok'}).name, 'ok');
    expect(fixtureValueProvider, isNotNull);
  });
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


def assert_valid_fixture(package: Path) -> None:
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
    if analyzer_version is None or not analyzer_version.group(1).startswith('12.'):
        actual = analyzer_version.group(1) if analyzer_version else 'missing'
        raise SystemExit(f'expected analyzer 12.x, resolved {actual}')
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
        package / 'lib/fixture_router.g.dart',
    ]
    absent = [str(path.relative_to(package)) for path in generated if not path.exists()]
    if absent:
        raise SystemExit(f'expected generated outputs missing: {absent}')
    required_output_tokens = {
        'fixture_model.freezed.dart': 'FixtureModel',
        'fixture_model.g.dart': 'FixtureModelFromJson',
        'fixture_provider.g.dart': 'fixtureValueProvider',
        'hive_adapters.g.dart': 'FixtureModelAdapter',
        'fixture_router.g.dart': 'FixtureRoute',
    }
    for name, token in required_output_tokens.items():
        text = (package / 'lib' / name).read_text()
        if token not in text:
            raise SystemExit(f'generated output {name} lacks expected symbol evidence')


def assert_web_build(package: Path) -> None:
    required = [
        package / 'build/web/index.html',
        package / 'build/web/flutter_bootstrap.js',
    ]
    absent = [str(path.relative_to(package)) for path in required if not path.exists()]
    if absent:
        raise SystemExit(f'web build output missing: {absent}')


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='flutter-skill-generator-') as directory:
        package = Path(directory)
        (package / 'lib').mkdir()
        (package / 'test').mkdir()
        (package / 'web').mkdir()
        (package / 'pubspec.yaml').write_text(PUBSPEC)
        (package / 'build.yaml').write_text(BUILD_YAML)
        (package / 'lib/fixture_model.dart').write_text(MODEL)
        (package / 'lib/fixture_provider.dart').write_text(PROVIDER)
        (package / 'lib/hive_adapters.dart').write_text(HIVE)
        (package / 'lib/fixture_router.dart').write_text(ROUTER)
        (package / 'lib/main.dart').write_text(MAIN)
        (package / 'web/index.html').write_text(WEB_INDEX)
        (package / 'test/fixture_test.dart').write_text(TEST)

        run(['flutter', 'pub', 'get'], package)
        run(['dart', 'run', 'build_runner', 'build'], package)
        assert_valid_fixture(package)
        run(['dart', 'analyze'], package, required_output=('No issues found!',))
        run(['flutter', 'analyze'], package, required_output=('No issues found!',))
        run(['flutter', 'test'], package, required_output=('All tests passed!',))
        run(['flutter', 'build', 'web', '--no-pub'], package)
        assert_web_build(package)

        (package / 'pubspec_overrides.yaml').write_text(
            'dependency_overrides:\n  analyzer: 14.1.0\n'
        )
        result = subprocess.run(
            ['flutter', 'pub', 'get'], cwd=package, text=True, capture_output=True
        )
        if result.returncode == 0:
            override_lock = (package / 'pubspec.lock').read_text()
            if 'version: "14.1.0"' not in override_lock:
                raise SystemExit('analyzer override was not reflected in the lockfile')
            incompatible = subprocess.run(
                ['dart', 'run', 'build_runner', 'build'],
                cwd=package,
                text=True,
                capture_output=True,
            )
            if incompatible.returncode == 0:
                raise SystemExit(
                    'unsupported analyzer override still ran the generator stack successfully'
                )
            output = incompatible.stdout + incompatible.stderr
            if not re.search(r'(?i)(error|failed|analy|version|builder)', output):
                raise SystemExit(
                    'unsupported analyzer override failed without a diagnostic explaining the incompatibility'
                )
            print('UNSUPPORTED_ANALYZER_OVERRIDE_REJECTED_BY_GENERATOR')
        else:
            output = result.stdout + result.stderr
            if 'analyzer' not in output.lower() or not re.search(
                r'(?i)(failed|incompat|version|could not|because)', output
            ):
                raise SystemExit(
                    'unsupported analyzer override was rejected without solver evidence'
                )
            print('UNSUPPORTED_ANALYZER_OVERRIDE_REJECTED_BY_SOLVER')

    print('COMPATIBILITY_FIXTURE_OK')


if __name__ == '__main__':
    main()
