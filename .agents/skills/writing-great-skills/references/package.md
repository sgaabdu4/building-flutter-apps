# Package review

Scope = frontmatter + `SKILL.md` + linked references + scripts/assets + `agents/openai.yaml` when present. Apply this skill to its own edits too.

| Surface | Check |
| --- | --- |
| Frontmatter | `name` + concise `description`; purpose + distinct trigger first. |
| References | Clear load condition + valid direct link; conditional detail stays out of entrypoint. Load only applicable routes. |
| Scripts/assets | Current consumer + concrete need; scripts execute successfully, assets serve actual output. |
| `agents/openai.yaml` | Optional UI/invocation/tool metadata; preserve useful existing fields. Add only for a current UI/configuration need. |
| UI fields | `display_name`, concise `short_description`, `default_prompt` explicitly invoking `$skill-name`; keep consistent with actual behavior. |
| Invocation | Use host-native `$`/`/` invocation; explicit-only only when user requests. Preserve existing policy unless change authorized. |
| Client policy | Codex: `agents/openai.yaml` → `policy.allow_implicit_invocation`. Claude: frontmatter → `disable-model-invocation`. `user-invocable` controls user access/menu visibility, not automatic selection. Verify target-host semantics. |
| Dependencies | Referenced skills/tools/files exist in target environment; no unavailable or machine-specific prerequisites disguised as portable guidance. |
| Migration | Review the whole package; classify keep/combine/discard by behavior, not file count. Preserve intent; remove stale commands + obsolete integration machinery. |

Validation = native validator + metadata/link checks + relevant script/behavior proof. Supported client field rejected → narrow schema/type fix at validator owner; retain unknown-field rejection. Substantial trigger change → matching + nearby nonmatching requests. Report untested behavior; structural success ≠ effective invocation.

Policy sources: [Codex](https://developers.openai.com/codex/skills/) · [Claude](https://code.claude.com/docs/en/skills).
