"""Use the consumer's Dart analyzer to prove omitted libraries have no counters."""

import json
import subprocess
import tempfile
from pathlib import Path

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


def erased_dart(files: set[Path], directory: Path) -> set[Path]:
    candidates = sorted(file for file in files if file.suffix == ".dart")
    registry = directory / ".dart_tool/package_config.json"
    if not candidates or not registry.is_file():
        return set()
    with tempfile.TemporaryDirectory(prefix="hard-eng-dart-parser-") as temporary:
        script = Path(temporary) / "classify.dart"
        script.write_text(PARSER)
        packages = f"--packages={registry.resolve()}"
        try:
            result = subprocess.run(
                ["dart", packages, str(script)],
                input=json.dumps([file.read_text() for file in candidates]) + "\n",
                text=True,
                capture_output=True,
                check=True,
                timeout=300,
            )
            outputs = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return set()  # Unavailable/incompatible parser cannot waive coverage.
    if not isinstance(outputs, list) or len(outputs) != len(candidates):
        return set()
    return {
        file for file, output in zip(candidates, outputs, strict=True) if output is True
    }
