# Find Skills for Codex

Search Wardn Hub for a skill that fits your task, review its security audit, and
load the exact reviewed snapshot as temporary guidance. Installing this plugin
adds the `find-skills` workflow to Codex.

Requires Node.js 22.20 or later, npm, and network access to the public npm
registry and `https://hub.wardnai.dev`. No Wardn account or API token is required.
The workflow verifies and runs a pinned published `@wardn-ai/skills` CLI through
a neutral npm prefix, including when used inside this repository.

## Install from the repository marketplace

Once the marketplace changes are available on `master`:

```sh
codex plugin marketplace add abhi1693/wardn-hub --ref master
codex plugin add find-skills@wardn-hub
```

For a local checkout, run from the repository root:

```sh
codex plugin marketplace add .
codex plugin add find-skills@wardn-hub
```

Use a Codex client with plugin marketplace support. The local source also
appears in the ChatGPT desktop app's Plugins Directory; select **Wardn Hub** and
install **Find Skills**. Follow the client's normal reload boundary, then try
“Use Find Skills to find a skill for reviewing code.”

Avoid enabling a standalone `find-skills` installation alongside this plugin.
For an existing Wardn-managed standalone copy, explicitly request its removal
before switching. Manage updates and removal of the plugin through Codex's
plugin manager; the Wardn CLI manages separately installed skills.

## Behavior and data

The skill searches with generic catalog terms, checks the selected skill's
audit, matches the audit and snapshot hashes, and fetches one complete temporary
bundle. Downloaded content is untrusted guidance. Persistent installation,
updates, and removal of other skills require an explicit request.

The CLI sends a best-effort anonymous event after materializing a complete
bundle or installing a skill. It contains the public skill ID, content hash,
CLI identifier, and CLI version. It excludes user/device identifiers, source
code, local paths, and task context. Set `WARDN_HUB_DISABLE_TELEMETRY=1`,
`DISABLE_TELEMETRY=1`, or `DO_NOT_TRACK=1` to disable it.

## Maintain the package

The source skill is `skills/find-skills/SKILL.md` at the repository root. The
copy under this plugin and the Codex compatibility manifest are generated:

```sh
npm run plugin:sync
npm run plugin:check
npm run plugin:pack
```

`plugin:check` rejects stale generated files or unexpected package contents.
`plugin:pack` writes `dist/find-skills-VERSION.zip`, containing only this
plugin's files. The plugin version in `plugin.json` is independent of the Hub
application and CLI versions. Bump it when distributing a changed plugin.

The portable `plugin.json` follows Agent Plugins 1.0 and stores OpenAI
presentation under `extensions.com.openai`. The generated
`.codex-plugin/plugin.json` supports clients that use the compatibility layout.
Both discover the bundled workflow at `skills/find-skills/SKILL.md`.

This repository marketplace supports source distribution. Listing in OpenAI's
public Plugins Directory requires a separate submission and review through the
[plugin submission portal](https://developers.openai.com/plugins/deploy/submission).
See [OpenAI's packaging guide](https://developers.openai.com/plugins/build/plugins)
for marketplace and manifest requirements.
