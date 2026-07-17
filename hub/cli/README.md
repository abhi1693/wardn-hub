# @wardn-ai/skills

Search, audit, fetch, and manage complete, hash-identified agent skill bundles from
[Wardn Hub](https://hub.wardnai.dev).

## Discover and load a skill

The CLI includes the full resolver workflow used by Wardn's `find-skills` skill:

```sh
npx -y @wardn-ai/skills search "code audit" --limit 8 --json
npx -y @wardn-ai/skills audit owner/repository/skill-slug --json
npx -y @wardn-ai/skills inspect owner/repository/skill-slug --json
npx -y @wardn-ai/skills fetch-bundle owner/repository/skill-slug --json
```

These examples use the latest published release. Append an exact version, for
example `@wardn-ai/skills@0.1.4`, when you want to pin the CLI.

`search` returns a bounded compact result set. `audit` normalizes the latest
decision for each audit provider and reports hard rejects, warnings, historical
failures, and the audited content hash. `inspect` validates the root `SKILL.md`
without printing it. `fetch-bundle` fetches the latest snapshot by default and
writes the complete validated bundle to a private temporary directory described
by its JSON manifest. Pass `--hash <sha256>` to require an exact snapshot instead.

Compatibility commands `fetch` and `fetch-chunk` can retrieve the root Markdown.
They do not replace `fetch-bundle` when a skill has scripts, references, or assets.

## Install, update, and remove

Run the CLI without installing it globally:

```sh
npx @wardn-ai/skills install owner/repository/skill-slug -g -a codex
npx @wardn-ai/skills update skill-slug -g -a codex
npx @wardn-ai/skills remove skill-slug -g -a codex -y
```

`install` is also available as `add` or `i`. `remove` is also available as
`delete`, `uninstall`, or `rm`.

Project installs are the default. Pass `--global` to use the selected agent's
user-level skills directory, or `--target /absolute/skills/directory` when the
host exposes a custom directory. Supported built-in targets are `codex`,
`claude-code`, `cursor`, `opencode`, `gemini-cli`, `github-copilot`, and
`universal`. Repeat `--agent` to install to multiple agents.

Omit `--hash` to use the latest Wardn snapshot, or pass `--hash <sha256>` to
require a specific snapshot. The CLI refuses
path traversal, symlink targets, malformed or oversized bundles, unmanaged
directory collisions, and updates whose Wardn ownership marker names a
different skill. Installs and updates are staged on the target filesystem and
retain the prior managed installation until replacement succeeds.

A matching legacy `find-skills` installation created by Wardn's former shell
self-installer is migrated automatically to the current ownership marker and
script-free bundle. Unrelated or malformed `find-skills` directories remain
untouched.

To install or update the script-free Wardn discovery skill itself:

```sh
npx -y @wardn-ai/skills install abhi1693/wardn-hub/find-skills \
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
WARDN_HUB_DISABLE_TELEMETRY=1 npx @wardn-ai/skills install ...
DISABLE_TELEMETRY=1 npx @wardn-ai/skills install ...
DO_NOT_TRACK=1 npx @wardn-ai/skills install ...
npx @wardn-ai/skills install ... --no-telemetry
```

Self-hosted development instances can set `WARDN_HUB_API_BASE_URL`. HTTPS is
required except for `localhost` and `127.0.0.1`.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
