#!/usr/bin/env python3
"""Sync, check, and package Find Skills without application build dependencies."""

import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "find-skills"


def prepare(sync: bool) -> list[Path]:
    if PLUGIN.is_symlink() or any(path.is_symlink() for path in PLUGIN.rglob("*")):
        raise ValueError("symlinks are not allowed in the plugin")
    manifest = json.loads((PLUGIN / "plugin.json").read_text())
    if (
        manifest.get("$schema")
        != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    ):
        raise ValueError("plugin.json must declare the Agent Plugins 1.0 schema")
    if manifest.get("name") != PLUGIN.name:
        raise ValueError("plugin name must match its directory")
    if not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", manifest["version"]
    ):
        raise ValueError("use a stable semantic plugin version")
    interface = manifest["extensions"]["com.openai"]["interface"]
    if not 1 <= len(interface["shortDescription"]) <= 30:
        raise ValueError("plugin subtitle must be 1-30 characters")

    legacy = {
        key: value
        for key, value in manifest.items()
        if key not in {"$schema", "extensions"}
    }
    legacy.update(skills="./skills/", interface=interface)
    generated = {
        ".codex-plugin/plugin.json": (json.dumps(legacy, indent=2) + "\n").encode(),
        "skills/find-skills/SKILL.md": (
            ROOT / "skills/find-skills/SKILL.md"
        ).read_bytes(),
        "skills/find-skills/LICENSE": (
            ROOT / "skills/find-skills/LICENSE"
        ).read_bytes(),
        "LICENSE": (ROOT / "LICENSE").read_bytes(),
    }
    expected = {"plugin.json", "README.md", *generated}
    for relative, contents in generated.items():
        target = PLUGIN / relative
        if sync:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        if not target.is_file() or target.read_bytes() != contents:
            raise ValueError(f"{relative} is stale; run npm run plugin:sync")

    files = []
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file():
            files.append(path)
    if {str(path.relative_to(PLUGIN)) for path in files} != expected:
        raise ValueError(
            "unexpected or missing plugin files; review the package inventory"
        )

    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    entry = next(
        item for item in marketplace["plugins"] if item["name"] == manifest["name"]
    )
    if entry["source"] != {"source": "local", "path": "./plugins/find-skills"}:
        raise ValueError(
            "marketplace source must point to the self-contained plugin directory"
        )
    if entry["policy"] != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        raise ValueError(
            "marketplace must offer optional installation with explicit policy"
        )
    if entry["category"] != interface["category"]:
        raise ValueError("marketplace and plugin categories must agree")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync", action="store_true", help="refresh generated plugin files"
    )
    parser.add_argument(
        "--pack", action="store_true", help="write a standalone plugin ZIP"
    )
    parser.add_argument("--output", type=Path, help="ZIP destination (implies --pack)")
    args = parser.parse_args()
    files = prepare(args.sync)
    print(f"Find Skills plugin verified ({len(files)} files)")
    if args.pack or args.output:
        version = json.loads((PLUGIN / "plugin.json").read_text())["version"]
        output = (args.output or ROOT / "dist" / f"find-skills-{version}.zip").resolve()
        if output.is_relative_to(PLUGIN):
            raise ValueError("write the archive outside the plugin directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, f"find-skills/{path.relative_to(PLUGIN)}")
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError("plugin archive failed its integrity check")
            for path in files:
                if (
                    archive.read(f"find-skills/{path.relative_to(PLUGIN)}")
                    != path.read_bytes()
                ):
                    raise ValueError(f"archive differs from source: {path}")
        print(output)


if __name__ == "__main__":
    main()
