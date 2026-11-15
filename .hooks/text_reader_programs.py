"""The reader programs that run beside the parser of each screen language, as text."""

JS_READER = r"""import { readFileSync } from "node:fs";
import { parseSync } from "oxc-parser";

const request = JSON.parse(readFileSync(0, "utf8"));
const INLINE = new Set(request.inline);
const TEXT_PROPS = new Set(request.text_props);
const SKIP = new Set(request.skip);
const STORED = new Set(request.stored);
const TAP_NAMES = new Set(request.tap_names);
const TAP_ATTRS = new Set(request.tap_attrs);
const USER = request.user;
const SLOT = { x: 1 };
const NO_CLAMP = 1000;
const LISTS = new Set(["map", "flatMap", "filter"]);
const LETTER = /[\p{L}\p{N}]/u;
const CLAMP_STYLES = new Set(["WebkitLineClamp", "lineClamp"]);
const WRAPPERS = new Set(["ParenthesizedExpression", "TSAsExpression", "TSSatisfiesExpression", "TSNonNullExpression", "ChainExpression", "TSTypeAssertion"]);

let starts = [0];
let blocks = [];

function lineOf(offset) {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= offset) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

function span(from, to) {
  const out = [];
  for (let line = lineOf(from); line <= lineOf(Math.max(from, to - 1)); line++) out.push(line);
  return out;
}

function unwrap(node) {
  while (node && WRAPPERS.has(node.type)) node = node.expression;
  return node;
}

function elementName(node) {
  const name = node.openingElement ? node.openingElement.name : null;
  if (!name) return "";
  if (name.type === "JSXIdentifier") return name.name;
  if (name.type === "JSXMemberExpression") return name.property.name;
  return "";
}

function attrName(attr) {
  if (attr.type !== "JSXAttribute") return "";
  return attr.name.type === "JSXIdentifier" ? attr.name.name : "";
}

function keyName(property) {
  if (property.computed) return "";
  const key = property.key;
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") return key.value;
  return "";
}

function stringOf(node) {
  node = unwrap(node);
  if (!node) return null;
  if (node.type === "Literal" && typeof node.value === "string") return [node.value];
  if (node.type === "TemplateLiteral") {
    const parts = [];
    node.quasis.forEach((quasi, index) => {
      parts.push(quasi.value.cooked ?? quasi.value.raw);
      if (index < node.expressions.length) parts.push(SLOT);
    });
    return parts;
  }
  if (node.type === "ConditionalExpression") {
    const a = stringOf(node.consequent);
    const b = stringOf(node.alternate);
    if (a || b) return [{ alt: [a ?? [SLOT], b ?? [SLOT]] }];
  }
  if (node.type === "LogicalExpression") {
    const right = stringOf(node.right);
    if (!right) return null;
    return node.operator === "&&" ? right : [{ alt: [[SLOT], right] }];
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    const left = stringOf(node.left);
    const right = stringOf(node.right);
    if (left || right) return [...(left ?? [SLOT]), ...(right ?? [SLOT])];
  }
  return null;
}

function storedField(node) {
  node = unwrap(node);
  if (!node) return "";
  if (node.type === "MemberExpression") {
    if (!node.computed && node.property.type === "Identifier" && STORED.has(node.property.name)) return node.property.name;
    return "";
  }
  if (node.type === "CallExpression") {
    const callee = node.callee;
    if (callee.type !== "MemberExpression" || LISTS.has(callee.property.name)) return "";
    return storedField(callee.object);
  }
  if (node.type === "LogicalExpression") {
    return node.operator === "&&" ? storedField(node.right) : storedField(node.left) || storedField(node.right);
  }
  if (node.type === "ConditionalExpression") return storedField(node.consequent) || storedField(node.alternate);
  return "";
}

function holdsJsx(node) {
  let found = false;
  walkAll(node, (child) => {
    if (child.type === "JSXElement" || child.type === "JSXFragment") found = true;
    return !found;
  });
  return found;
}

function children(node) {
  const out = [];
  for (const key in node) {
    if (key === "parent") continue;
    const value = node[key];
    if (Array.isArray(value)) {
      for (const item of value) if (item && typeof item.type === "string") out.push(item);
    } else if (value && typeof value.type === "string") out.push(value);
  }
  return out;
}

function walkAll(node, visit) {
  if (!node || typeof node.type !== "string") return;
  if (visit(node) === false) return;
  for (const child of children(node)) walkAll(child, visit);
}

function cleanText(raw) {
  const lines = raw.split(/\r\n|\n|\r/);
  let out = "";
  lines.forEach((line, index) => {
    let text = line.replace(/\t/g, " ");
    if (index !== 0) text = text.replace(/^ +/, "");
    if (index !== lines.length - 1) text = text.replace(/ +$/, "");
    if (text) out += (out && index !== 0 ? " " : "") + text;
  });
  return out;
}

function hasText(parts) {
  return parts.some((part) => {
    if (typeof part === "string") return LETTER.test(part);
    if (part.alt) return part.alt.some(hasText);
    return Boolean(part.field);
  });
}

function stringLiterals(node, out) {
  walkAll(node, (child) => {
    if (child.type === "Literal" && typeof child.value === "string") out.push(child.value);
    if (child.type === "TemplateElement") out.push(child.value.cooked ?? child.value.raw);
    return true;
  });
  return out;
}

function classClamp(tokens) {
  let best = null;
  for (const token of tokens) {
    const name = token.slice(token.lastIndexOf(":") + 1);
    let value = null;
    let found = /^line-clamp-(\d+)$/.exec(name) || /^line-clamp-\[(\d+)\]$/.exec(name);
    if (found) value = Number(found[1]);
    else if (name === "truncate") value = 1;
    else if (name === "line-clamp-none") value = NO_CLAMP;
    if (value !== null && (best === null || value > best)) best = value;
  }
  return best;
}

function styleClamp(expression) {
  let best = null;
  walkAll(expression, (child) => {
    if (child.type === "Property" && CLAMP_STYLES.has(keyName(child))) {
      const value = unwrap(child.value);
      if (value && value.type === "Literal") {
        const number = typeof value.value === "number" ? value.value : Number(value.value);
        if (Number.isFinite(number) && (best === null || number > best)) best = number;
      }
    }
    return true;
  });
  return best;
}

function traits(node, name) {
  let clamp = null;
  let tap = TAP_NAMES.has(name);
  for (const attr of node.openingElement.attributes) {
    const key = attrName(attr);
    if (TAP_ATTRS.has(key)) tap = true;
    const container = attr.value && attr.value.type === "JSXExpressionContainer" ? attr.value.expression : attr.value;
    let found = null;
    if (key === "className" || key === "class") {
      found = classClamp(stringLiterals(container, []).flatMap((text) => text.split(/\s+/)));
    } else if (key === "style") found = styleClamp(container);
    else if (key === "numberOfLines") {
      const value = unwrap(container);
      if (value && value.type === "Literal" && typeof value.value === "number") found = value.value;
    }
    if (found !== null && (clamp === null || found > clamp)) clamp = found;
  }
  return { clamp, tap, tags: span(node.openingElement.start, node.openingElement.end) };
}

function context(stack) {
  let clamp = null;
  let tap = false;
  let user = false;
  for (let index = stack.length - 1; index >= 0; index--) {
    if (clamp === null && stack[index].clamp !== null) clamp = stack[index].clamp;
    tap = tap || stack[index].tap;
    user = user || stack[index].user;
  }
  return { clamp, tap, user };
}

function holdsField(parts) {
  return parts.some((part) => typeof part !== "string" && (part.field || (part.alt && part.alt.some(holdsField))));
}

function emit(kind, name, parts, rawLines, stack) {
  const own = [...new Set(rawLines)];
  if (!hasText(parts) || own.length === 0) return;
  const lines = holdsField(parts) ? [...new Set([...own, ...stack.flatMap((entry) => entry.tags)])] : own;
  if (request.touched && !lines.some((line) => request.touched.has(line))) return;
  const { clamp, tap, user } = context(stack);
  blocks.push({ line: Math.min(...own), lines, kind, name, parts, clamp, tap, user });
}

function visitAttributes(node, stack) {
  for (const attr of node.openingElement.attributes) {
    if (attr.type !== "JSXAttribute") {
      walkInto(attr, stack);
      continue;
    }
    const key = attrName(attr);
    const container = attr.value && attr.value.type === "JSXExpressionContainer" ? attr.value.expression : attr.value;
    if (TEXT_PROPS.has(key)) {
      const parts = stringOf(container);
      if (parts) emit("prop", key, parts, span(attr.start, attr.end), stack);
    }
    if (key === "dangerouslySetInnerHTML" && container) {
      walkAll(container, (child) => {
        if (child.type === "Property" && keyName(child) === "__html" && storedField(child.value)) {
          emit("prop", key, [{ x: 1, field: storedField(child.value) }], span(attr.start, attr.end), stack);
        }
        return true;
      });
    }
    if (container) walkInto(container, stack);
  }
}

function walkInto(node, stack) {
  walkAll(node, (child) => visit(child, stack));
}

function expressionParts(expression, stack, from, to) {
  if (holdsJsx(expression)) {
    walkInto(expression, stack);
    const inner = stringOf(expression);
    return inner ? { parts: inner, lines: span(from, to) } : { parts: [], lines: [] };
  }
  const field = storedField(expression);
  if (field) return { parts: [{ x: 1, field }], lines: span(from, to) };
  const parts = stringOf(expression);
  if (parts) return { parts, lines: span(from, to) };
  return { parts: [SLOT], lines: [] };
}

function visitElement(node, stack) {
  const name = elementName(node);
  if (SKIP.has(name)) return;
  const own = traits(node, name);
  const next = [...stack, { ...own, user: name === USER }];
  visitAttributes(node, next);
  collect(node.children, name, next, name);
}

function collect(nodes, name, stack, parent) {
  let block = { parts: [], lines: [] };
  const cut = () => {
    emit("jsx", name, block.parts, block.lines, stack);
    block = { parts: [], lines: [] };
  };
  const gather = (list, owner) => {
    for (const child of list) {
      if (child.type === "JSXText") {
        const text = cleanText(child.value);
        if (text.trim()) {
          block.parts.push(text);
          const lead = child.value.length - child.value.trimStart().length;
          const tail = child.value.length - child.value.trimEnd().length;
          block.lines.push(...span(child.start + lead, child.end - tail));
        } else if (text) block.parts.push(text);
      } else if (child.type === "JSXExpressionContainer") {
        if (child.expression.type === "JSXEmptyExpression") continue;
        const found = expressionParts(child.expression, stack, child.start, child.end);
        block.parts.push(...found.parts);
        block.lines.push(...found.lines);
      } else if (child.type === "JSXFragment") gather(child.children, owner);
      else if (child.type === "JSXElement") {
        const childName = elementName(child);
        if (childName === "code" && SKIP.has("code")) block.parts.push(SLOT);
        else if (childName === "br" || SKIP.has(childName)) cut();
        else if (INLINE.has(childName) || (childName === "Text" && owner === "Text")) {
          const own = traits(child, childName);
          stack = [...stack, { ...own, user: childName === USER }];
          visitAttributes(child, stack);
          gather(child.children, childName);
          stack = stack.slice(0, -1);
        } else {
          cut();
          visitElement(child, stack);
        }
      }
    }
  };
  gather(nodes, parent);
  cut();
}

function constantParts(node) {
  node = unwrap(node);
  if (!node) return [];
  if (node.type === "ArrayExpression") {
    return node.elements.map((element) => ({ parts: stringOf(element), node: element })).filter((entry) => entry.parts);
  }
  const parts = stringOf(node);
  return parts ? [{ parts, node }] : [];
}

function skipsObject(node) {
  return node.properties.some((property) => property.type === "Property" && ["@context", "@type"].includes(keyName(property)));
}

function visit(node, stack) {
  if (node.type === "JSXElement") {
    visitElement(node, stack);
    return false;
  }
  if (node.type === "JSXFragment") {
    collect(node.children, "", stack, "");
    return false;
  }
  if (node.type === "ExportNamedDeclaration" && node.declaration) {
    const declaration = node.declaration;
    const id = declaration.type === "VariableDeclaration" ? declaration.declarations[0]?.id : declaration.id;
    if (id && (id.name === "metadata" || id.name === "generateMetadata")) return false;
  }
  if (node.type === "ObjectExpression" && skipsObject(node)) return false;
  if (node.type === "Property" && TEXT_PROPS.has(keyName(node))) {
    const parts = stringOf(node.value);
    if (parts) emit("key", keyName(node), parts, span(node.start, node.end), stack);
  }
  if (node.type === "VariableDeclarator" && node.id.type === "Identifier" && node.init) {
    for (const entry of constantParts(node.init)) {
      const text = entry.parts.filter((part) => typeof part === "string").join("");
      if (/\s/.test(text.trim())) emit("const", node.id.name, entry.parts, span(entry.node.start, entry.node.end), stack);
    }
  }
  return true;
}

function errorLine(error) {
  const label = error.labels && error.labels[0];
  return `line ${label ? lineOf(label.start) : 1}: ${error.message}`;
}

const files = [];
for (const file of request.files) {
  starts = [0];
  for (let index = 0; index < file.source.length; index++) if (file.source.charCodeAt(index) === 10) starts.push(index + 1);
  blocks = [];
  request.touched = file.touched ? new Set(file.touched) : null;
  const result = parseSync(file.path, file.source);
  const failure = result.errors.find((error) => error.severity === "Error");
  if (failure) {
    files.push({ path: file.path, error: errorLine(failure), blocks: [] });
    continue;
  }
  walkInto(result.program, []);
  files.push({ path: file.path, error: null, blocks });
}
process.stdout.write(JSON.stringify({ files }));
"""

DART_READER = r"""import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';
import 'package:analyzer/source/line_info.dart';

const slot = {'x': 1};
const noClamp = 1000;
const lists = {'map', 'where', 'expand', 'toList'};
final letter = RegExp(r'[\p{L}\p{N}]', unicode: true);
late Set<String> textProps, stored, tapNames, tapArgs;
late String userName;
Set<int>? touched;

class Builder {
  Builder(this.owner);
  final AstNode owner;
  final List<Object> parts = [];
  final List<int> lines = [];
}

ArgumentList? argsOf(AstNode node) {
  if (node is MethodInvocation) return node.argumentList;
  if (node is InstanceCreationExpression) return node.argumentList;
  return null;
}

String callName(AstNode node) {
  if (node is InstanceCreationExpression) {
    final type = node.constructorName.type.name.lexeme;
    final named = node.constructorName.name?.name;
    return named == null ? type : '$type.$named';
  }
  if (node is MethodInvocation) {
    final target = node.target;
    if (target == null) return node.methodName.name;
    if (target is SimpleIdentifier) return '${target.name}.${node.methodName.name}';
  }
  return '';
}

Expression? positional(ArgumentList args) {
  final first = args.arguments.firstOrNull;
  if (first == null || first is NamedArgument) return null;
  return first.argumentExpression;
}

NamedArgument? namedArgument(ArgumentList args, String name) {
  for (final argument in args.arguments.whereType<NamedArgument>()) {
    if (argument.name.lexeme == name) return argument;
  }
  return null;
}

Expression? unwrap(Expression? node) {
  while (node is ParenthesizedExpression) {
    node = node.expression;
  }
  return node;
}

List<Object>? parts(Expression? raw) {
  final node = unwrap(raw);
  if (node is SimpleStringLiteral) return [node.value];
  if (node is AdjacentStrings) {
    return [for (final part in node.strings) ...(parts(part) ?? [slot])];
  }
  if (node is StringInterpolation) {
    return [
      for (final element in node.elements)
        if (element is InterpolationString) element.value else slot
    ];
  }
  if (node is ConditionalExpression) {
    final a = parts(node.thenExpression);
    final b = parts(node.elseExpression);
    if (a == null && b == null) return null;
    return [
      {'alt': [a ?? [slot], b ?? [slot]]}
    ];
  }
  if (node is BinaryExpression) {
    final operator = node.operator.lexeme;
    if (operator == '??') {
      final right = parts(node.rightOperand);
      return right == null ? null : [{'alt': [[slot], right]}];
    }
    if (operator == '+') {
      final left = parts(node.leftOperand);
      final right = parts(node.rightOperand);
      if (left == null && right == null) return null;
      return [...(left ?? [slot]), ...(right ?? [slot])];
    }
  }
  return null;
}

String storedField(Expression? raw) {
  final node = unwrap(raw);
  if (node is PrefixedIdentifier) {
    return stored.contains(node.identifier.name) ? node.identifier.name : '';
  }
  if (node is PropertyAccess) {
    return stored.contains(node.propertyName.name) ? node.propertyName.name : '';
  }
  if (node is PostfixExpression) return storedField(node.operand);
  if (node is MethodInvocation) {
    return lists.contains(node.methodName.name) ? '' : storedField(node.target);
  }
  if (node is BinaryExpression) {
    if (node.operator.lexeme == '&&') return storedField(node.rightOperand);
    final left = storedField(node.leftOperand);
    return left.isNotEmpty ? left : storedField(node.rightOperand);
  }
  if (node is ConditionalExpression) {
    final then = storedField(node.thenExpression);
    return then.isNotEmpty ? then : storedField(node.elseExpression);
  }
  return '';
}

bool hasText(List<Object> list) => list.any((part) {
      if (part is String) return letter.hasMatch(part);
      final map = part as Map;
      if (map.containsKey('alt')) {
        return (map['alt'] as List).any((branch) => hasText((branch as List).cast<Object>()));
      }
      return map.containsKey('field');
    });

class Reader extends RecursiveAstVisitor<void> {
  Reader(this.path, this.info, this.blocks);
  final String path;
  final LineInfo info;
  final List<Object> blocks;
  final Set<AstNode> consumed = {};

  int lineOf(int offset) => info.getLocation(offset).lineNumber;

  List<int> span(AstNode node) => [
        for (var line = lineOf(node.offset); line <= lineOf(node.end > node.offset ? node.end - 1 : node.offset); line++) line
      ];

  Map<String, Object?> context(AstNode? owner) {
    int? clamp;
    var tap = false;
    var user = false;
    final path = <AstNode>{};
    for (AstNode? up = owner; up != null; up = up.parent) {
      path.add(up);
    }
    final own = owner == null ? null : argsOf(owner);
    final lines = own == null ? null : namedArgument(own, 'maxLines')?.argumentExpression;
    if (lines is IntegerLiteral) clamp = lines.value;
    for (AstNode? up = owner; up != null; up = up.parent) {
      final args = argsOf(up);
      if (args == null) continue;
      final name = callName(up);
      if (name == userName) user = true;
      if (tapNames.contains(name)) tap = true;
      for (final argument in args.arguments.whereType<NamedArgument>()) {
        if (tapArgs.contains(argument.name.lexeme) && !path.contains(argument)) tap = true;
      }
    }
    return {'clamp': clamp, 'tap': tap, 'user': user};
  }

  List<int> tagLines(AstNode? owner) {
    final out = <int>[];
    for (AstNode? up = owner; up != null; up = up.parent) {
      final args = argsOf(up);
      if (args == null) continue;
      out.add(lineOf(up.offset));
      for (final argument in args.arguments.whereType<NamedArgument>()) {
        out.add(lineOf(argument.offset));
      }
    }
    return out;
  }

  void emit(String kind, String name, List<Object> found, List<int> raw, AstNode? owner) {
    final own = raw.toSet().toList();
    if (!hasText(found) || own.isEmpty) return;
    final field = found.any((part) => part is Map && part.containsKey('field'));
    final lines = field ? {...own, ...tagLines(owner)}.toList() : own;
    final only = touched;
    if (only != null && !lines.any(only.contains)) return;
    blocks.add({
      'line': own.reduce((a, b) => a < b ? a : b),
      'lines': lines,
      'kind': kind,
      'name': name,
      'parts': found,
      ...context(owner),
    });
  }

  void flush(Builder builder, String name) {
    emit('jsx', name, [...builder.parts], [...builder.lines], builder.owner);
    builder.parts.clear();
    builder.lines.clear();
  }

  void spanInto(AstNode node, Builder builder, String name) {
    consumed.add(node);
    final args = argsOf(node)!;
    final text = namedArgument(args, 'text');
    if (text != null) {
      consumed.add(text);
      final found = parts(text.argumentExpression) ?? [slot];
      final field = storedField(text.argumentExpression);
      builder.parts.addAll(field.isNotEmpty ? [{'x': 1, 'field': field}] : found);
      builder.lines.addAll(span(text));
    }
    final children = namedArgument(args, 'children')?.argumentExpression;
    if (children is! ListLiteral) return;
    for (final element in children.elements) {
      if (element is! Expression) continue;
      final inner = unwrap(element);
      final kind = inner == null ? '' : callName(inner);
      if (inner != null && kind == 'TextSpan') {
        spanInto(inner, builder, name);
      } else if (kind == 'WidgetSpan') {
        flush(builder, name);
      } else {
        builder.parts.add(slot);
      }
    }
  }

  void widget(AstNode node, ArgumentList args, String name) {
    if (name == 'Text' || name == 'SelectableText') {
      final first = positional(args);
      if (first == null) return;
      final field = storedField(first);
      final found = field.isNotEmpty ? [{'x': 1, 'field': field}] : parts(first);
      if (found != null) emit('jsx', name, found, span(first), node);
    } else if (name == 'Text.rich' || name == 'SelectableText.rich' || name == 'RichText' || name == 'TextSpan') {
      final builder = Builder(node);
      final source = name == 'RichText'
          ? namedArgument(args, 'text')?.argumentExpression
          : name == 'TextSpan' ? (node as Expression) : positional(args);
      final inner = unwrap(source);
      if (inner == null || callName(inner) != 'TextSpan') return;
      spanInto(inner, builder, name);
      flush(builder, name);
    }
  }

  void call(AstNode node) {
    final args = argsOf(node);
    if (args == null || consumed.contains(node)) return;
    widget(node, args, callName(node));
    for (final argument in args.arguments.whereType<NamedArgument>()) {
      final key = argument.name.lexeme;
      if (!textProps.contains(key) || consumed.contains(argument)) continue;
      final found = parts(argument.argumentExpression);
      if (found != null) emit('prop', key, found, span(argument), node);
    }
  }

  @override
  void visitMethodInvocation(MethodInvocation node) {
    call(node);
    super.visitMethodInvocation(node);
  }

  @override
  void visitInstanceCreationExpression(InstanceCreationExpression node) {
    call(node);
    super.visitInstanceCreationExpression(node);
  }

  @override
  void visitSetOrMapLiteral(SetOrMapLiteral node) {
    final entries = node.elements.whereType<MapLiteralEntry>().toList();
    final structural = entries.any((entry) {
      final key = unwrap(entry.key);
      return key is SimpleStringLiteral && (key.value == '@context' || key.value == '@type');
    });
    if (structural) return;
    for (final entry in entries) {
      final key = unwrap(entry.key);
      if (key is! SimpleStringLiteral || !textProps.contains(key.value)) continue;
      final found = parts(entry.value);
      if (found != null) emit('key', key.value, found, span(entry), null);
    }
    super.visitSetOrMapLiteral(node);
  }

  @override
  void visitVariableDeclaration(VariableDeclaration node) {
    final init = unwrap(node.initializer);
    final values = init is ListLiteral
        ? init.elements.whereType<Expression>().toList()
        : init == null ? <Expression>[] : [init];
    for (final value in values) {
      final found = parts(value);
      if (found == null) continue;
      final text = found.whereType<String>().join();
      if (RegExp(r'\s').hasMatch(text.trim())) {
        emit('const', node.name.lexeme, found, span(value), null);
      }
    }
    super.visitVariableDeclaration(node);
  }
}

Future<void> main() async {
  final input = jsonDecode(await stdin.transform(utf8.decoder).join()) as Map<String, dynamic>;
  textProps = (input['text_props'] as List).cast<String>().toSet();
  stored = (input['stored'] as List).cast<String>().toSet();
  tapNames = (input['tap_names'] as List).cast<String>().toSet();
  tapArgs = (input['tap_attrs'] as List).cast<String>().toSet();
  userName = input['user'] as String;
  final files = <Object>[];
  for (final file in input['files'] as List) {
    final path = file['path'] as String;
    final wanted = file['touched'] as List?;
    touched = wanted?.cast<int>().toSet();
    final parsed = parseString(content: file['source'] as String, path: path, throwIfDiagnostics: false);
    final blocks = <Object>[];
    String? error;
    if (parsed.errors.isNotEmpty) {
      final first = parsed.errors.first;
      error = 'line ${parsed.lineInfo.getLocation(first.offset).lineNumber}: ${first.message}';
    } else {
      parsed.unit.accept(Reader(path, parsed.lineInfo, blocks));
    }
    files.add({'path': path, 'error': error, 'blocks': blocks});
  }
  stdout.write(jsonEncode({'files': files}));
}
"""
