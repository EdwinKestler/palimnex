# Phase 4 reviewer launch commands

Every Grok invocation for Phase 4, copied from the Desktop Commander tool history on the device
(`~/.claude-server-commander/tool-history.jsonl`). `$P` is `artifacts/ontology/phase-4`.
`--disallowed-tools Write` removes only the file-writing tool; shell access remains
(`--permission-mode bypassPermissions`), so reviewer read-only status is verified
separately by the ownership snapshot audits (`integration/ownership-audit.*.json`).

- 2026-11-07T03:32:25.808Z

```bash
nohup grok --prompt-file $P/integration/grok-review-wave1-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-review-wave1.log 2>&1 &
```

- 2026-11-07T03:56:07.871Z

```bash
nohup grok --prompt-file $P/integration/grok-rereview-cohort-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-rereview-cohort.log 2>&1 &
```

- 2026-11-07T04:22:29.064Z

```bash
nohup grok --prompt-file $P/integration/grok-review-wave23-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-review-wave23.log 2>&1 &
```

- 2026-11-07T04:59:05.379Z

```bash
nohup grok --prompt-file $P/integration/grok-rereview-evaluation-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-rereview-evaluation.log 2>&1 &
```

- 2026-11-07T05:25:19.353Z

```bash
nohup grok --prompt-file $P/integration/grok-review-integration-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-review-integration.log 2>&1 &
```

- 2026-11-07T05:46:12.081Z

```bash
nohup grok --prompt-file $P/integration/grok-rereview-integration-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-rereview-integration.log 2>&1 &
```

- 2026-11-07T06:02:31.486Z

```bash
nohup grok --prompt-file $P/integration/grok-rereview2-integration-prompt.md -m grok-4.6 --reasoning-effort xhigh --disallowed-tools Write --disable-web-search --no-subagents --permission-mode bypassPermissions --output-format plain --cwd "$PWD" > $P/logs/grok-rereview2-integration.log 2>&1 &
```
