import { createHash, randomBytes, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

export const MANIFEST_FILENAME = ".tacroman-workspace.json";
export const FRAGMENT_SUFFIX = ".tacroman.json";
const WORKSPACE_FORMAT = "tacroman-workspace";
const FRAGMENT_FORMAT = "tacroman-fragment";
const FORMAT_VERSION = 1;

export const DEFAULT_WORKSPACE_PROFILE: Record<string, unknown> = {
  schema_version: 2,
  id: "acronym-package",
  name: "acronym package (input file)",
  description: "Produces an acronym environment and independent command definitions for the acronym package.",
  preamble_hint: "In the preamble: \\usepackage[printonlyused]{acronym}",
  header: "\\begin{acronym}\n",
  footer: "\n\\end{acronym}\n",
  separator: "\n",
  sort_by: "short",
  escape_mode: "none",
  usage_template: "",
  commands: [
    {
      id: "acronym",
      label: "Acronym",
      description: "A standard \\acro definition.",
      template: "\\acro{[[short]]}{[[long]]}",
      usage_template: "\\ac{[[short]]}",
      fields: [
        {
          id: "short", label: "Short form", required: true, comparison_group: "acronym-key",
          similarity_group: "short-form", warn_whitespace: true, warn_braces: true,
        },
        {
          id: "long", label: "Long form", required: true, similarity_group: "long-form",
          warn_trailing_punctuation: true,
        },
        { id: "category", label: "Category" },
        { id: "note", label: "Note", multiline: true },
      ],
    },
    {
      id: "acroplural",
      label: "Plural definition",
      description: "An independent \\acroplural command definition.",
      template: "\\acroplural{[[key]]}[[short_plural]]{[[long_plural]]}",
      sort_by: "key",
      fields: [
        {
          id: "key", label: "Acronym key", required: true, comparison_group: "acronym-key",
          similarity_group: "short-form",
        },
        { id: "short_plural", label: "Short plural", output_template: "[[[value]]]" },
        { id: "long_plural", label: "Long plural", required: true, similarity_group: "long-form" },
      ],
    },
  ],
};

export interface WorkspaceOwner {
  installation_id: string;
  display_name: string;
  created_at: string;
  suffix: string;
}

export interface WorkspaceEntry {
  uid: string;
  commandId: string;
  values: Record<string, string>;
}

export interface WorkspaceSource {
  entry: WorkspaceEntry;
  owner: WorkspaceOwner;
  fragmentPath: string;
  entryIndex: number;
}

export interface MergedWorkspaceEntry extends WorkspaceEntry {
  localUid?: string;
  editable: boolean;
  sources: WorkspaceSource[];
}

export interface WorkspaceConflict {
  id: string;
  label: string;
  localUids: string[];
  variants: Array<WorkspaceSource & { editable: boolean }>;
}

export interface WorkspaceSnapshot {
  workspacePath: string;
  workspaceId: string;
  workspaceName: string;
  profile: Record<string, unknown>;
  revision: string;
  localFragmentPath: string;
  localOwner: WorkspaceOwner;
  localEntries: WorkspaceEntry[];
  entries: MergedWorkspaceEntry[];
  conflicts: WorkspaceConflict[];
  fragmentCount: number;
  exportBlocked: boolean;
}

export class WorkspaceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkspaceError";
  }
}

export class WorkspaceConflictError extends WorkspaceError {
  constructor() {
    super("The workspace changed outside this editor. Reload it before saving again.");
    this.name = "WorkspaceConflictError";
  }
}

function isObject(raw: unknown): raw is Record<string, unknown> {
  return Boolean(raw) && typeof raw === "object" && !Array.isArray(raw);
}

function uuid(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new WorkspaceError(`${label} is not a valid UUID.`);
  }
  return value.toLowerCase();
}

async function readJson(filePath: string): Promise<{ raw: Record<string, unknown>; content: string }> {
  let content: string;
  try {
    content = await readFile(filePath, "utf8");
  } catch (error) {
    throw new WorkspaceError(`Could not read ${path.basename(filePath)}: ${error instanceof Error ? error.message : String(error)}`);
  }
  try {
    const raw = JSON.parse(content) as unknown;
    if (!isObject(raw)) throw new Error("the root value is not an object");
    return { raw, content };
  } catch (error) {
    throw new WorkspaceError(`${path.basename(filePath)} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function marker(raw: Record<string, unknown>, format: string, filePath: string): void {
  if (raw.format !== format || raw.format_version !== FORMAT_VERSION) {
    throw new WorkspaceError(`${path.basename(filePath)} is not a supported ${format} file.`);
  }
}

function values(raw: unknown): Record<string, string> {
  if (!isObject(raw)) return {};
  return Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, value === null || value === undefined ? "" : String(value)]));
}

function entries(raw: unknown, filePath: string): WorkspaceEntry[] {
  if (!Array.isArray(raw)) throw new WorkspaceError(`${path.basename(filePath)} does not contain an entries array.`);
  const seen = new Set<string>();
  return raw.map((item) => {
    if (
      !isObject(item)
      || typeof item.uid !== "string" || !item.uid
      || typeof item.command_id !== "string" || !item.command_id
      || !isObject(item.values)
      || Object.entries(item.values).some(([key, value]) => !key || typeof value !== "string")
    ) throw new WorkspaceError(`${path.basename(filePath)} contains an invalid schema-v2 entry.`);
    if (seen.has(item.uid)) throw new WorkspaceError(`${path.basename(filePath)} contains the duplicate UID ${item.uid}.`);
    seen.add(item.uid);
    return {
      uid: item.uid,
      commandId: item.command_id,
      values: values(item.values),
    };
  });
}

function utcTimestamp(raw: unknown, label: string): string {
  if (typeof raw !== "string" || !raw.endsWith("Z") || Number.isNaN(Date.parse(raw))) {
    throw new WorkspaceError(`${label} is not a UTC ISO timestamp.`);
  }
  return raw;
}

function validateProfile(raw: Record<string, unknown>): void {
  const identifier = /^[A-Za-z][A-Za-z0-9._-]*$/;
  const fieldIdentifier = /^[A-Za-z][A-Za-z0-9_]*$/;
  if (
    typeof raw.id !== "string" || !identifier.test(raw.id)
    || typeof raw.name !== "string" || !raw.name.trim()
    || !Array.isArray(raw.commands) || !raw.commands.length
    || (raw.escape_mode !== undefined && !["none", "latex", "csv"].includes(String(raw.escape_mode)))
  ) {
    throw new WorkspaceError("The workspace manifest does not contain a usable profile.");
  }
  const commandIds = new Set<string>();
  for (const command of raw.commands) {
    if (
      !isObject(command)
      || typeof command.id !== "string" || !identifier.test(command.id)
      || commandIds.has(command.id)
      || typeof command.template !== "string" || !command.template
      || !Array.isArray(command.fields) || !command.fields.length
    ) {
      throw new WorkspaceError("The workspace manifest contains an invalid command profile.");
    }
    commandIds.add(command.id);
    const fieldIds = new Set<string>();
    for (const field of command.fields) {
      if (
        !isObject(field)
        || typeof field.id !== "string" || !fieldIdentifier.test(field.id)
        || fieldIds.has(field.id)
        || (field.output_template !== undefined && !String(field.output_template).includes("[[value]]"))
      ) throw new WorkspaceError(`The workspace manifest contains an invalid field in ${command.id}.`);
      fieldIds.add(field.id);
    }
    const sortBy = typeof command.sort_by === "string" ? command.sort_by.trim() : "";
    if (sortBy && sortBy !== "none" && sortBy !== "id" && !fieldIds.has(sortBy)) {
      throw new WorkspaceError(`The workspace manifest contains an invalid sort field in ${command.id}.`);
    }
  }
}

function owner(raw: unknown, filePath: string): WorkspaceOwner {
  if (!isObject(raw)) throw new WorkspaceError(`${path.basename(filePath)} contains invalid owner metadata.`);
  const result = {
    installation_id: uuid(raw.installation_id, "owner.installation_id"),
    display_name: typeof raw.display_name === "string" ? raw.display_name.trim() : "",
    created_at: utcTimestamp(raw.created_at, "owner.created_at"),
    suffix: typeof raw.suffix === "string" ? raw.suffix.trim() : "",
  };
  if (!result.display_name || !result.created_at || !/^[A-Za-z0-9]{8}$/.test(result.suffix)) {
    throw new WorkspaceError(`${path.basename(filePath)} contains invalid owner metadata.`);
  }
  return result;
}

function normalized(value: string, caseSensitive: boolean): string {
  const result = value.normalize("NFKC").trim().replace(/\s+/g, " ");
  return caseSensitive ? result : result.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
}

function compareUtf8(left: string, right: string): number {
  return Buffer.from(left, "utf8").compare(Buffer.from(right, "utf8"));
}

function commandDefinitions(profile: Record<string, unknown>): Map<string, Record<string, unknown>> {
  const raw = Array.isArray(profile.commands) ? profile.commands : [];
  return new Map(raw.flatMap((item): Array<[string, Record<string, unknown>]> =>
    isObject(item) && typeof item.id === "string" ? [[item.id, item]] : []
  ));
}

function fieldDefinitions(command: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(command.fields) ? command.fields.filter(isObject) : [];
}

function sameIdentity(left: WorkspaceEntry, right: WorkspaceEntry, commands: Map<string, Record<string, unknown>>): boolean {
  if (left.uid === right.uid) return true;
  if (left.commandId !== right.commandId) return false;
  const command = commands.get(left.commandId);
  if (!command) return false;
  const fields = fieldDefinitions(command);
  for (const leftField of fields) {
    const group = typeof leftField.comparison_group === "string" ? leftField.comparison_group.trim() : "";
    const leftId = typeof leftField.id === "string" ? leftField.id : "";
    const leftValue = left.values[leftId]?.trim() ?? "";
    if (!group || !leftValue) continue;
    for (const rightField of fields) {
      if (rightField.comparison_group !== group || typeof rightField.id !== "string") continue;
      const rightValue = right.values[rightField.id]?.trim() ?? "";
      if (!rightValue) continue;
      const caseSensitive = leftField.case_sensitive === true && rightField.case_sensitive === true;
      if (normalized(leftValue, caseSensitive) === normalized(rightValue, caseSensitive)) return true;
    }
  }
  return false;
}

function exactContent(entry: WorkspaceEntry): string {
  return JSON.stringify([
    entry.commandId,
    Object.entries(entry.values)
      .map(([key, value]) => [key, value.replace(/\r\n?/g, "\n")])
      .sort(([left], [right]) => compareUtf8(left, right)),
  ]);
}

function sourceMarker(source: WorkspaceSource): string {
  return `${path.basename(source.fragmentPath)}\0${String(source.entryIndex).padStart(8, "0")}\0${source.entry.uid}`;
}

function labelFor(entry: WorkspaceEntry, profile: Record<string, unknown>): string {
  const command = commandDefinitions(profile).get(entry.commandId);
  if (command) {
    const fields = fieldDefinitions(command);
    for (const field of fields.filter((item) => typeof item.comparison_group === "string" && item.comparison_group)) {
      if (typeof field.id === "string" && entry.values[field.id]?.trim()) return entry.values[field.id].trim();
    }
    for (const field of fields) {
      if (typeof field.id === "string" && entry.values[field.id]?.trim()) return entry.values[field.id].trim();
    }
  }
  return entry.uid;
}

function mergeSources(
  sources: WorkspaceSource[],
  profile: Record<string, unknown>,
  installationId: string,
): { entries: MergedWorkspaceEntry[]; conflicts: WorkspaceConflict[] } {
  const commands = commandDefinitions(profile);
  const parents = sources.map((_, index) => index);
  const find = (start: number): number => {
    let index = start;
    while (parents[index] !== index) {
      parents[index] = parents[parents[index]];
      index = parents[index];
    }
    return index;
  };
  const union = (left: number, right: number): void => {
    const first = find(left);
    const second = find(right);
    if (first !== second) parents[second] = first;
  };
  for (let left = 0; left < sources.length; left += 1) {
    for (let right = left + 1; right < sources.length; right += 1) {
      if (sameIdentity(sources[left].entry, sources[right].entry, commands)) union(left, right);
    }
  }
  const clusters = new Map<number, WorkspaceSource[]>();
  sources.forEach((source, index) => {
    const root = find(index);
    clusters.set(root, [...(clusters.get(root) ?? []), source]);
  });
  const ordered = [...clusters.values()].sort((left, right) =>
    compareUtf8(
      sourceMarker(left.slice().sort((a, b) => compareUtf8(sourceMarker(a), sourceMarker(b)))[0]),
      sourceMarker(right.slice().sort((a, b) => compareUtf8(sourceMarker(a), sourceMarker(b)))[0]),
    )
  );
  const merged: MergedWorkspaceEntry[] = [];
  const conflicts: WorkspaceConflict[] = [];
  for (const cluster of ordered) {
    cluster.sort((left, right) => compareUtf8(sourceMarker(left), sourceMarker(right)));
    const variants = new Set(cluster.map((source) => exactContent(source.entry)));
    const local = cluster.filter((source) => source.owner.installation_id === installationId);
    if (variants.size === 1) {
      merged.push({
        ...cluster[0].entry,
        localUid: local[0]?.entry.uid,
        editable: Boolean(local.length),
        sources: cluster,
      });
      continue;
    }
    conflicts.push({
      id: createHash("sha256").update(cluster.map(sourceMarker).join("\0")).digest("hex").slice(0, 16),
      label: labelFor(cluster[0].entry, profile),
      localUids: local.map((source) => source.entry.uid),
      variants: cluster.map((source) => ({ ...source, editable: source.owner.installation_id === installationId })),
    });
  }
  return { entries: merged, conflicts };
}

export function previewLocalEntries(
  snapshot: WorkspaceSnapshot,
  localEntries: WorkspaceEntry[],
): { entries: MergedWorkspaceEntry[]; conflicts: WorkspaceConflict[] } {
  const foreign = new Map<string, WorkspaceSource>();
  const collect = (source: WorkspaceSource): void => {
    if (source.owner.installation_id === snapshot.localOwner.installation_id) return;
    foreign.set(sourceMarker(source), source);
  };
  for (const entry of snapshot.entries) for (const source of entry.sources) collect(source);
  for (const conflict of snapshot.conflicts) for (const source of conflict.variants) collect(source);
  const localSources = localEntries.map((entry, entryIndex): WorkspaceSource => ({
    entry,
    owner: snapshot.localOwner,
    fragmentPath: snapshot.localFragmentPath,
    entryIndex,
  }));
  return mergeSources([...foreign.values(), ...localSources], snapshot.profile, snapshot.localOwner.installation_id);
}

async function atomicWriteJson(filePath: string, payload: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

function fragmentPayload(workspaceId: string, fragmentOwner: WorkspaceOwner, fragmentEntries: WorkspaceEntry[]): unknown {
  return {
    format: FRAGMENT_FORMAT,
    format_version: FORMAT_VERSION,
    workspace_id: workspaceId,
    owner: fragmentOwner,
    payload: {
      schema_version: 2,
      entries: fragmentEntries.map((entry) => ({
        uid: entry.uid,
        command_id: entry.commandId,
        values: entry.values,
      })),
    },
  };
}

export async function loadWorkspace(workspacePath: string, installationId: string): Promise<WorkspaceSnapshot> {
  const root = path.resolve(workspacePath);
  const manifestPath = path.join(root, MANIFEST_FILENAME);
  const manifestFile = await readJson(manifestPath);
  marker(manifestFile.raw, WORKSPACE_FORMAT, manifestPath);
  const workspaceId = uuid(manifestFile.raw.workspace_id, "workspace_id");
  if (typeof manifestFile.raw.name !== "string" || !manifestFile.raw.name.trim()) throw new WorkspaceError("The workspace manifest does not contain a workspace name.");
  utcTimestamp(manifestFile.raw.created_at, "created_at");
  if (!isObject(manifestFile.raw.profile)) throw new WorkspaceError("The workspace manifest does not contain a usable profile.");
  validateProfile(manifestFile.raw.profile);
  const names = (await readdir(root)).filter((name) => name.endsWith(FRAGMENT_SUFFIX)).sort(compareUtf8);
  if (!names.length) throw new WorkspaceError("The workspace does not contain a participant fragment.");
  const revisionParts = [MANIFEST_FILENAME, manifestFile.content];
  const seenOwners = new Set<string>();
  const sources: WorkspaceSource[] = [];
  let localFragmentPath = "";
  let localOwner: WorkspaceOwner | undefined;
  let localEntries: WorkspaceEntry[] = [];
  for (const name of names) {
    const filePath = path.join(root, name);
    const file = await readJson(filePath);
    marker(file.raw, FRAGMENT_FORMAT, filePath);
    if (uuid(file.raw.workspace_id, "workspace_id") !== workspaceId) {
      throw new WorkspaceError(`${name} belongs to another TAcroMan workspace.`);
    }
    const fragmentOwner = owner(file.raw.owner, filePath);
    if (name !== fragmentFilename(fragmentOwner)) throw new WorkspaceError(`${name} does not match its owner metadata.`);
    if (seenOwners.has(fragmentOwner.installation_id)) {
      throw new WorkspaceError(`Installation ${fragmentOwner.display_name} owns more than one fragment.`);
    }
    seenOwners.add(fragmentOwner.installation_id);
    if (!isObject(file.raw.payload) || file.raw.payload.schema_version !== 2) {
      throw new WorkspaceError(`${name} does not contain a supported entry payload.`);
    }
    const fragmentEntries = entries(file.raw.payload.entries, filePath);
    revisionParts.push(name, file.content);
    if (fragmentOwner.installation_id === installationId) {
      localFragmentPath = filePath;
      localOwner = fragmentOwner;
      localEntries = fragmentEntries;
    }
    fragmentEntries.forEach((entry, entryIndex) => sources.push({ entry, owner: fragmentOwner, fragmentPath: filePath, entryIndex }));
  }
  if (!localOwner || !localFragmentPath) throw new WorkspaceError("This installation does not own a fragment in the workspace.");
  const merged = mergeSources(sources, manifestFile.raw.profile, installationId);
  return {
    workspacePath: root,
    workspaceId,
    workspaceName: typeof manifestFile.raw.name === "string" ? manifestFile.raw.name : path.basename(root),
    profile: manifestFile.raw.profile,
    revision: createHash("sha256").update(revisionParts.join("\0")).digest("hex"),
    localFragmentPath,
    localOwner,
    localEntries,
    entries: merged.entries,
    conflicts: merged.conflicts,
    fragmentCount: names.length,
    exportBlocked: Boolean(merged.conflicts.length),
  };
}

function safeName(value: string): string {
  return value.normalize("NFKC").trim()
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ").replace(/[ .]+$/g, "").slice(0, 48) || "user";
}

function base62(bytes: Buffer): string {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  let number = BigInt(`0x${bytes.toString("hex")}`);
  let result = "";
  for (let index = 0; index < 8; index += 1) {
    result += alphabet[Number(number % 62n)];
    number /= 62n;
  }
  return result;
}

function defaultDisplayName(): string {
  try {
    return os.userInfo().username;
  } catch {
    return process.env.USERNAME || process.env.USER || "user";
  }
}

export function newOwner(installationId: string, displayName?: string): WorkspaceOwner {
  const createdAt = new Date().toISOString();
  const name = safeName(displayName || defaultDisplayName());
  const digest = createHash("sha256").update(`${name}\0${createdAt}\0${randomBytes(16).toString("hex")}`).digest();
  return { installation_id: uuid(installationId, "installation_id"), display_name: name, created_at: createdAt, suffix: base62(digest) };
}

export function fragmentFilename(fragmentOwner: WorkspaceOwner): string {
  return `${safeName(fragmentOwner.display_name)}_${fragmentOwner.suffix}${FRAGMENT_SUFFIX}`;
}

export async function createWorkspace(
  workspacePath: string,
  installationId: string,
  profile: Record<string, unknown>,
  displayName?: string,
): Promise<WorkspaceSnapshot> {
  const root = path.resolve(workspacePath);
  await mkdir(root, { recursive: true });
  const existing = await readdir(root);
  if (existing.includes(MANIFEST_FILENAME) || existing.some((name) => name.endsWith(FRAGMENT_SUFFIX))) {
    throw new WorkspaceError("The selected folder already contains a TAcroMan workspace or fragments.");
  }
  const workspaceId = randomUUID();
  const manifest = {
    format: WORKSPACE_FORMAT,
    format_version: FORMAT_VERSION,
    workspace_id: workspaceId,
    name: path.basename(root) || "TAcroMan",
    created_at: new Date().toISOString(),
    profile,
  };
  const fragmentOwner = newOwner(installationId, displayName);
  await atomicWriteJson(path.join(root, MANIFEST_FILENAME), manifest);
  await atomicWriteJson(path.join(root, fragmentFilename(fragmentOwner)), fragmentPayload(workspaceId, fragmentOwner, []));
  return loadWorkspace(root, installationId);
}

export async function joinWorkspace(workspacePath: string, installationId: string): Promise<WorkspaceSnapshot> {
  try {
    return await loadWorkspace(workspacePath, installationId);
  } catch (error) {
    if (!(error instanceof WorkspaceError) || !error.message.includes("does not own a fragment")) throw error;
  }
  const root = path.resolve(workspacePath);
  const manifestFile = await readJson(path.join(root, MANIFEST_FILENAME));
  marker(manifestFile.raw, WORKSPACE_FORMAT, path.join(root, MANIFEST_FILENAME));
  const workspaceId = uuid(manifestFile.raw.workspace_id, "workspace_id");
  let fragmentOwner = newOwner(installationId);
  let target = path.join(root, fragmentFilename(fragmentOwner));
  while (true) {
    try {
      await stat(target);
      fragmentOwner = newOwner(installationId);
      target = path.join(root, fragmentFilename(fragmentOwner));
    } catch {
      break;
    }
  }
  await atomicWriteJson(target, fragmentPayload(workspaceId, fragmentOwner, []));
  return loadWorkspace(root, installationId);
}

export async function saveLocalEntries(
  workspacePath: string,
  installationId: string,
  expectedRevision: string,
  localEntries: WorkspaceEntry[],
): Promise<WorkspaceSnapshot> {
  const current = await loadWorkspace(workspacePath, installationId);
  if (current.revision !== expectedRevision) throw new WorkspaceConflictError();
  await atomicWriteJson(current.localFragmentPath, fragmentPayload(current.workspaceId, current.localOwner, localEntries));
  return loadWorkspace(workspacePath, installationId);
}

export async function saveWorkspaceProfile(
  workspacePath: string,
  installationId: string,
  expectedRevision: string,
  profile: Record<string, unknown>,
): Promise<WorkspaceSnapshot> {
  const current = await loadWorkspace(workspacePath, installationId);
  if (current.revision !== expectedRevision) throw new WorkspaceConflictError();
  const manifestPath = path.join(current.workspacePath, MANIFEST_FILENAME);
  const manifest = await readJson(manifestPath);
  manifest.raw.profile = profile;
  await atomicWriteJson(manifestPath, manifest.raw);
  return loadWorkspace(workspacePath, installationId);
}

export async function renameParticipant(
  workspacePath: string,
  installationId: string,
  expectedRevision: string,
  displayName: string,
): Promise<WorkspaceSnapshot> {
  const current = await loadWorkspace(workspacePath, installationId);
  if (current.revision !== expectedRevision) throw new WorkspaceConflictError();
  const renamedOwner = { ...current.localOwner, display_name: safeName(displayName) };
  const target = path.join(current.workspacePath, fragmentFilename(renamedOwner));
  const sameTarget = process.platform === "win32"
    ? target.toLocaleLowerCase() === current.localFragmentPath.toLocaleLowerCase()
    : target === current.localFragmentPath;
  if (!sameTarget) {
    try {
      await stat(target);
      throw new WorkspaceError(`${path.basename(target)} already exists.`);
    } catch (error) {
      if (error instanceof WorkspaceError) throw error;
    }
  }
  await atomicWriteJson(current.localFragmentPath, fragmentPayload(current.workspaceId, renamedOwner, current.localEntries));
  if (path.basename(target) !== path.basename(current.localFragmentPath)) await rename(current.localFragmentPath, target);
  return loadWorkspace(workspacePath, installationId);
}

export function legacyEntries(raw: unknown): WorkspaceEntry[] {
  const records = Array.isArray(raw)
    ? raw
    : isObject(raw) && Array.isArray(raw.entries)
      ? raw.entries
      : isObject(raw) && Array.isArray(raw.acronyms)
        ? raw.acronyms
        : null;
  if (!records) throw new WorkspaceError("The selected legacy database does not contain entries.");
  return records.flatMap((item): WorkspaceEntry[] => {
    if (!isObject(item)) return [];
    const storedValues = isObject(item.values)
      ? values(item.values)
      : values({ short: item.short, long: item.long, category: item.category, note: item.note });
    return [{
      uid: typeof item.uid === "string" && item.uid ? item.uid : randomUUID(),
      commandId: typeof item.command_id === "string" && item.command_id ? item.command_id : "acronym",
      values: storedValues,
    }];
  });
}
