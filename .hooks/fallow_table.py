"""Every setting `fallow config` prints has a class; a setting without one is refused."""

from collections.abc import Callable

from fallow_report import HEALTH_LIMITS

GLOB_CHARACTERS = "*?[{"
FALLOW_KEYS = {
    "entry": "named",
    "dynamicallyLoaded": "named",
    "ignoreExports": "named",
    "ignorePatterns": "free",
    "ignoreFindings": "equal",
    "framework": "equal",
    "workspaces": "equal",
    "ignoreDependencies": "used",
    "ignoreUnresolvedImports": "equal",
    "ignoreDependencyOverrides": "equal",
    "rulePacks": "free",
    "ignoreExportsUsedInFile": "equal",
    "usedClassMembers": "equal",
    "duplicates.enabled": "equal",
    "duplicates.mode": "equal",
    "duplicates.near": "free",
    "duplicates.minTokens": "limit",
    "duplicates.minLines": "limit",
    "duplicates.minOccurrences": "limit",
    "duplicates.threshold": "limit",
    "duplicates.ignore": "patterns",
    "duplicates.ignoredClones": "equal",
    "duplicates.ignoreDefaults": "equal",
    "duplicates.skipLocal": "equal",
    "duplicates.ignoreSymlinks": "equal",
    "duplicates.crossLanguage": "free",
    "duplicates.ignoreImports": "equal",
    "duplicates.normalization": "equal",
    "duplicates.minCorpusSizeForShingleFilter": "free",
    "duplicates.minCorpusSizeForTokenCache": "free",
    "similarCode.threshold": "limit",
    "similarCode.minLines": "limit",
    "similarCode.ignore": "patterns",
    "health.maxCyclomatic": "limit",
    "health.maxCognitive": "limit",
    "health.maxCrap": "limit",
    "health.maxUnitSize": "limit",
    "health.crapRefactorBand": "free",
    "health.coverage": "proved",
    "health.coverageRoot": "free",
    "health.ignore": "patterns",
    "health.suggestInlineSuppression": "equal",
    "health.inlineThresholdOverrides": "free",
    "health.thresholdOverrides": "limits",
    "rules": "rules",
    "overrides": "rules",
    "security": "equal",
    "resolve": "equal",
    "production": "equal",
    "plugins": "equal",
    "publicPackages": "equal",
    "sealed": "equal",
    "includeEntryExports": "free",
    "autoImports": "equal",
    "failOnParseError": "free",
    "showCascade": "free",
}
FALLOW_PREFIXES = {
    "health.ownership.": "free",
    "health.changeCoupling.": "free",
    "boundaries": "proved",
    "flags": "free",
    "fix": "free",
}
HEALTH_KEYS = {
    "health.maxCyclomatic": "max_cyclomatic_threshold",
    "health.maxCognitive": "max_cognitive_threshold",
    "health.maxCrap": "max_crap_threshold",
    "health.maxUnitSize": "max_unit_size_threshold",
}


def flatten(config: dict[str, object], prefix: str = "") -> dict[str, object]:
    """Each printed setting under its dotted name; a map with entries is read through."""
    found: dict[str, object] = {}
    for key, value in config.items():
        name = f"{prefix}{key}"
        free = any(name.startswith(item) for item in FALLOW_PREFIXES)
        if isinstance(value, dict) and value and not free and name != "rules":
            found.update(flatten(value, name + "."))
        else:
            found[name] = value
    return found


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    return []


def number(value: object) -> float | None:
    return (
        None
        if isinstance(value, bool) or not isinstance(value, (int, float))
        else float(value)
    )


def rule_hits(config: dict[str, object], defaults: dict[str, object]) -> list[str]:
    base = defaults.get("rules")
    base = base if isinstance(base, dict) else {}
    overrides = config.get("overrides")
    sets = [config.get("rules")]
    hits = []
    for item in overrides if isinstance(overrides, list) else []:
        extra = (
            sorted(set(item) - {"files", "rules"})
            if isinstance(item, dict)
            else ["entry"]
        )
        hits += [f"overrides entry sets {key}, which no table classes" for key in extra]
        sets.append(item.get("rules") if isinstance(item, dict) else None)
    for rules in sets:
        for name, level in rules.items() if isinstance(rules, dict) else []:
            if name.startswith("complexity-") and level != "error":
                hits.append(f"rule {name} is {level}, below error")
            elif level == "off" and base.get(name) != "off":
                hits.append(f"rule {name} is off")
    return hits


def limit_hit(name: str, value: object, default: object) -> list[str]:
    now, base = number(value), number(default)
    if name in HEALTH_KEYS:
        base = float(HEALTH_LIMITS[HEALTH_KEYS[name]])
    if (
        now is None
        or base is None
        or now > base
        or (name == "health.maxCrap" and now <= 0)
    ):
        return [f"{name} is {value!r}, above the limit {base}"]
    return []


def override_limit_hits(value: object) -> list[str]:
    hits = []
    for item in value if isinstance(value, list) else []:
        for key, name in HEALTH_KEYS.items():
            field = key.removeprefix("health.")
            if isinstance(item, dict) and field in item:
                hits += limit_hit(
                    f"health.thresholdOverrides[{field}]",
                    item[field],
                    HEALTH_LIMITS[name],
                )
    return hits


def named_hit(name: str, text: str, covered: Callable[[str], str]) -> str:
    """A glob entry is refused; it is told to go when a plugin or a package script already finds every file it names."""
    if name == "entry" and (found := covered(text)):
        return (
            f"{name} lists {text!r}: Fallow's {found} already finds "
            "these files; remove the entry"
        )
    return (
        f"{name} lists {text!r}, a glob that marks many files; list each file by name"
    )


NATIVE_PROOF = (
    "capacitor.config.*, AndroidManifest.xml, Podfile, Package.swift or build.gradle*"
)


def unproved(text: str) -> bool:
    return False


def judge_key(
    name: str,
    value: object,
    default: object,
    drop: Callable[[list[str]], list[str]],
    covered: Callable[[str], str],
    used: Callable[[str], bool] = unproved,
) -> list[str]:
    kind = FALLOW_KEYS.get(name)
    if kind is None and not any(name.startswith(item) for item in FALLOW_PREFIXES):
        if value == default:
            return []
        return [
            f"{name} is set to {value!r}, not its default {default!r}, and no table classes it: remove it from the project's Fallow config or set it back to its default"
        ]
    if kind == "equal" and value != default:
        return [f"{name} is {value!r}, not Fallow's default {default!r}"]
    if kind == "limit":
        return limit_hit(name, value, default)
    if kind == "limits":
        return override_limit_hits(value)
    if kind == "named":
        return [
            named_hit(name, text, covered)
            for text in strings(value)
            if any(mark in text for mark in GLOB_CHARACTERS)
        ]
    if kind == "used":
        return [
            f"{name} lists {text!r}: Fallow cannot see where a package is used outside a JavaScript import, so the entry passes only when the name appears in a tracked {NATIVE_PROOF}; none does"
            for text in strings(value)
            if not used(text)
        ]
    if kind == "patterns":
        return [f"{name}: {hit}" for hit in drop(strings(value))]
    return []


def judge(
    config: dict[str, object],
    defaults: dict[str, object],
    drop: Callable[[list[str]], list[str]],
    covered: Callable[[str], str],
    used: Callable[[str], bool] = unproved,
) -> list[str]:
    """What the printed Fallow config does wrong, key by key, compared with Fallow's own defaults."""
    base = flatten(defaults)
    hits = rule_hits(config, defaults)
    for name, value in flatten(config).items():
        if name not in {"rules", "overrides"}:
            hits += judge_key(name, value, base.get(name), drop, covered, used)
    return hits
