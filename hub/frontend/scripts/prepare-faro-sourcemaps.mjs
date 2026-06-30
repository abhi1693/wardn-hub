import { mkdir, readdir, copyFile, rm } from "node:fs/promises";
import path from "node:path";

const nextDir = path.join(process.cwd(), ".next");
const publicStaticDir = path.join(nextDir, "static");
const privateMapRoot = path.join(nextDir, "faro-sourcemaps", "_next", "static");

async function walk(dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      return [];
    }
    throw error;
  }

  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".map")) {
      files.push(fullPath);
    }
  }
  return files;
}

const sourceMaps = await walk(publicStaticDir);

for (const sourceMap of sourceMaps) {
  const relativePath = path.relative(publicStaticDir, sourceMap);
  const privatePath = path.join(privateMapRoot, relativePath);

  await mkdir(path.dirname(privatePath), { recursive: true });
  await copyFile(sourceMap, privatePath);
  await rm(sourceMap);
}

console.log(`Prepared ${sourceMaps.length} Faro source maps.`);
