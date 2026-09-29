"""Prove omitted Dart libraries have no counters with Hard Eng's pinned analyzer."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

TOOL = Path(__file__).with_name("dart_declarations.pubspec.yaml")

PARSER = r"""
import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';

Iterable<AstNode> descendants(AstNode node) sync* {
  for (final child in node.childEntities.whereType<AstNode>()) {
    yield child;
    yield* descendants(child);
  }
}

bool erased(CompilationUnitMember node) {
  if (node is TopLevelVariableDeclaration) return node.variables.isConst;
  if (node is GenericTypeAlias || node is FunctionTypeAlias) return true;
  if (node is ClassDeclaration) {
    if (node.abstractKeyword == null && node.sealedKeyword == null) return false;
    return node.body.members.every(erasedClassMember);
  }
  if (node is EnumDeclaration) {
    return node.withClause == null && node.implementsClause == null &&
        node.body.members.every(erasedEnumMember);
  }
  return false;
}

// Enum values are const, so their constructors and final fields emit no counters.
bool erasedEnumMember(ClassMember member) {
  if (member is FieldDeclaration) {
    return member.isStatic ? member.fields.isConst : member.fields.isFinal;
  }
  if (member is ConstructorDeclaration) {
    return member.constKeyword != null && member.factoryKeyword == null &&
        member.body is EmptyFunctionBody;
  }
  return false;
}

bool erasedClassMember(ClassMember member) {
  if (member is MethodDeclaration) return member.body is EmptyFunctionBody;
  if (descendants(member).any((child) =>
      child is FormalParameterDefaultClause)) return false;
  if (member is FieldDeclaration) {
    return member.isStatic && member.fields.isConst;
  }
  if (member is ConstructorDeclaration) {
    return member.factoryKeyword != null &&
        member.redirectedConstructor != null &&
        member.body is EmptyFunctionBody;
  }
  return false;
}

void main() {
  final input = jsonDecode(stdin.readLineSync()!) as List<dynamic>;
  final result = input.map((source) {
    try {
      final parsed = parseString(content: source as String, throwIfDiagnostics: false);
      return parsed.errors.isEmpty && parsed.unit.declarations.every(erased);
    } catch (_) {
      return false;
    }
  }).toList();
  stdout.write(jsonEncode(result));
}
"""


def run_dart(
    arguments: list[str], package: Path, timeout: float, stdin: str | None = None
) -> str:
    step = "dart " + " ".join(arguments)
    try:
        result = subprocess.run(
            ["dart", *arguments],
            cwd=package,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(
            f"Dart declaration classifier failed at `{step}`: {error}"
        ) from error
    if result.returncode:
        output = (result.stderr.strip() or result.stdout.strip())[-4000:]
        raise ValueError(
            f"Dart declaration classifier failed at `{step}` "
            f"(exit {result.returncode}): {output}"
        )
    return result.stdout


def erased_dart(files: set[Path]) -> set[Path]:
    candidates = sorted(file for file in files if file.suffix == ".dart")
    if not candidates:
        return set()
    with tempfile.TemporaryDirectory(prefix="hard-eng-dart-parser-") as temporary:
        package = Path(temporary)
        shutil.copyfile(TOOL, package / "pubspec.yaml")
        shutil.copyfile(TOOL.with_suffix(".lock"), package / "pubspec.lock")
        (package / "classify.dart").write_text(PARSER)
        resolve = ["pub", "get", "--enforce-lockfile"]
        try:
            run_dart([*resolve, "--offline"], package, 120)
        except ValueError:
            run_dart(resolve, package, 120)
        output = run_dart(
            ["--packages=.dart_tool/package_config.json", "classify.dart"],
            package,
            300,
            json.dumps([file.read_text() for file in candidates]) + "\n",
        )
    try:
        outputs = json.loads(output)
    except ValueError:
        outputs = None
    if not isinstance(outputs, list) or len(outputs) != len(candidates):
        raise ValueError(
            f"Dart declaration classifier returned invalid output: {output[-4000:]}"
        )
    return {
        file for file, erased in zip(candidates, outputs, strict=True) if erased is True
    }
