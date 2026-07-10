import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pluginRoot = path.resolve(frontendRoot, "..");
const repositoryRoot = path.resolve(frontendRoot, "../../..");
const lock = JSON.parse(fs.readFileSync(path.join(frontendRoot, "package-lock.json"), "utf8"));
const packages = new Map();

function repositoryUrl(value) {
  const raw = typeof value === "string" ? value : value?.url || "";
  if (!raw) return "";
  if (/^[\w.-]+\/[\w.-]+$/.test(raw)) return `https://github.com/${raw}`;
  return raw.replace(/^git\+/, "").replace(/^git:\/\//, "https://").replace(/\.git$/, "");
}

function escapeCell(value) {
  return String(value || "").replaceAll("|", "\\|").replaceAll("\n", " ");
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

for (const [packagePath, entry] of Object.entries(lock.packages || {})) {
  if (!packagePath.startsWith("node_modules/") || entry.dev) continue;
  const directory = path.join(frontendRoot, packagePath);
  const metadata = JSON.parse(fs.readFileSync(path.join(directory, "package.json"), "utf8"));
  const key = `${metadata.name}@${entry.version}`;
  if (packages.has(key)) continue;
  const licenseFile = fs
    .readdirSync(directory)
    .find((name) => /^(license|licence)(\..*)?$/i.test(name));
  if (!licenseFile) throw new Error(`Missing license file for ${key}`);
  const licenseText = fs
    .readFileSync(path.join(directory, licenseFile), "utf8")
    .trim()
    .replaceAll("\r\n", "\n");
  packages.set(key, {
    key,
    name: metadata.name,
    version: entry.version,
    license: metadata.license || entry.license || "UNKNOWN",
    repository: repositoryUrl(metadata.repository),
    licenseText,
  });
}

const rows = [...packages.values()].sort((left, right) => left.key.localeCompare(right.key));
const licenseGroups = new Map();
for (const item of rows) {
  const hash = crypto.createHash("sha256").update(item.licenseText).digest("hex");
  const group = licenseGroups.get(hash) || { packages: [], text: item.licenseText };
  group.packages.push(item.key);
  licenseGroups.set(hash, group);
}

const output = [
  "# Third-Party Notices",
  "",
  "This file is generated from the bundled frontend production dependency tree. Run `npm run notices` after changing frontend dependencies.",
  "",
  "## Package Inventory",
  "",
  "| Package | Version | License | Repository |",
  "| --- | ---: | --- | --- |",
  ...rows.map((item) => {
    const repository = item.repository ? `[source](${item.repository})` : "-";
    return `| ${escapeCell(item.name)} | ${escapeCell(item.version)} | ${escapeCell(item.license)} | ${repository} |`;
  }),
  "",
  "## License Texts",
  "",
];

let index = 0;
for (const group of licenseGroups.values()) {
  index += 1;
  output.push(`### License ${index}`);
  output.push("");
  output.push(`Applies to: ${group.packages.map((item) => `\`${item}\``).join(", ")}`);
  output.push("");
  output.push(`<pre>${escapeHtml(group.text)}</pre>`);
  output.push("");
}

const notice = `${output.join("\n").trimEnd()}\n`;
fs.writeFileSync(path.join(repositoryRoot, "THIRD_PARTY_NOTICES.md"), notice, "utf8");
fs.writeFileSync(path.join(pluginRoot, "THIRD_PARTY_NOTICES.md"), notice, "utf8");
console.log(`Wrote ${rows.length} packages and ${licenseGroups.size} license texts.`);
