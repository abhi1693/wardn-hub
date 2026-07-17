# @wardn/skills

Search, audit, fetch, and manage complete, hash-identified agent skill bundles from
[Wardn Hub](https://hub.wardnai.dev).

## Discover and load a skill

The CLI includes the full resolver workflow used by Wardn's `find-skills` skill:

```sh
npx -y @wardn/skills search "code audit" --limit 8 --json
npx -y @wardn/skills audit owner/repository/skill-slug --json
npx -y @wardn/skills inspect owner/repository/skill-slug --json
npx -y @wardn/skills fetch-bundle owner/repository/skill-slug \
  --hash expected-64-character-sha256 \
  --json
```

`search` returns a bounded compact result set. `audit` normalizes the latest
decision for each audit provider and reports hard rejects, warnings, historical
failures, and the audited content hash. `inspect` validates the root `SKILL.md`
without printing it. `fetch-bundle` requires that exact hash and writes the
complete validated bundle to a private temporary directory described by its JSON
manifest.

Compatibility commands `fetch` and `fetch-chunk` can retrieve the root Markdown.
They do not replace `fetch-bundle` when a skill has scripts, references, or assets.

## Install, update, and remove

Run the CLI without installing it globally:

```sh
npx @wardn/skills install owner/repository/skill-slug -g -a codex
npx @wardn/skills update skill-slug -g -a codex
npx @wardn/skills remove skill-slug -g -a codex -y
```

`install` is also available as `add` or `i`. `remove` is also available as
`delete`, `uninstall`, or `rm`.

Project installs are the default. Pass `--global` to use the selected agent's
user-level skills directory, or `--target /absolute/skills/directory` when the
host exposes a custom directory. Supported built-in targets are `codex`,
`claude-code`, `cursor`, `opencode`, `gemini-cli`, `github-copilot`, and
`universal`. Repeat `--agent` to install to multiple agents.

Use `--hash <sha256>` to require a specific Wardn snapshot. The CLI refuses
path traversal, symlink targets, malformed or oversized bundles, unmanaged
directory collisions, and updates whose Wardn ownership marker names a
different skill. Installs and updates are staged on the target filesystem and
retain the prior managed installation until replacement succeeds.

To install or update the script-free Wardn discovery skill itself:

```sh
npx -y @wardn/skills install abhi1693/wardn-hub/find-skills \
  --global \
  --agent codex
```

## Telemetry

After a temporary complete bundle is materialized or a new installation succeeds,
the CLI sends one best-effort anonymous event containing only the public skill ID,
its content hash, the CLI identifier, and the CLI version. It does not send source
code, local paths, task context, user identifiers, or device identifiers.
Telemetry failures never fail or undo an operation.

Disable telemetry with any of:

```sh
WARDN_HUB_DISABLE_TELEMETRY=1 npx @wardn/skills install ...
DISABLE_TELEMETRY=1 npx @wardn/skills install ...
DO_NOT_TRACK=1 npx @wardn/skills install ...
npx @wardn/skills install ... --no-telemetry
```

Self-hosted development instances can set `WARDN_HUB_API_BASE_URL`. HTTPS is
required except for `localhost` and `127.0.0.1`.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
