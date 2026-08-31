import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { randomUUID } from "node:crypto";
import {
  createWorkspace,
  DEFAULT_WORKSPACE_PROFILE,
  joinWorkspace,
  loadWorkspace,
  renameParticipant,
  saveLocalEntries,
  WorkspaceConflictError,
  WorkspaceError,
} from "../src/workspace";

async function temporaryWorkspace(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(os.tmpdir(), "tacroman-workspace-"));
  try {
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("creates one readable fragment per installation and keeps suffix on rename", async () => {
  await temporaryWorkspace(async (root) => {
    const firstId = randomUUID();
    const secondId = randomUUID();
    const first = await createWorkspace(root, firstId, DEFAULT_WORKSPACE_PROFILE, "Peter");
    assert.match(path.basename(first.localFragmentPath), /^Peter_[A-Za-z0-9]{8}\.tacroman\.json$/);
    const suffix = first.localOwner.suffix;
    const joined = await joinWorkspace(root, secondId);
    assert.equal(joined.fragmentCount, 2);
    const renamed = await renameParticipant(root, firstId, (await loadWorkspace(root, firstId)).revision, "Peter Smith");
    assert.equal(renamed.localOwner.suffix, suffix);
    assert.equal(path.basename(renamed.localFragmentPath), `Peter Smith_${suffix}.tacroman.json`);
  });
});

test("merges identical profile-key duplicates and blocks divergent variants", async () => {
  await temporaryWorkspace(async (root) => {
    const firstId = randomUUID();
    const secondId = randomUUID();
    await createWorkspace(root, firstId, DEFAULT_WORKSPACE_PROFILE, "Peter");
    await joinWorkspace(root, secondId);
    let first = await loadWorkspace(root, firstId);
    await saveLocalEntries(root, firstId, first.revision, [{
      uid: randomUUID(), commandId: "acronym", values: { short: "AUV", long: "vehicle" },
    }]);
    let second = await loadWorkspace(root, secondId);
    const secondUid = randomUUID();
    await saveLocalEntries(root, secondId, second.revision, [{
      uid: secondUid, commandId: "acronym", values: { short: "AUV", long: "vehicle" },
    }]);
    first = await loadWorkspace(root, firstId);
    assert.equal(first.entries.length, 1);
    assert.equal(first.entries[0].sources.length, 2);
    assert.equal(first.conflicts.length, 0);

    second = await loadWorkspace(root, secondId);
    const conflicted = await saveLocalEntries(root, secondId, second.revision, [{
      uid: secondUid, commandId: "acronym", values: { short: "AUV", long: "different" },
    }]);
    assert.equal(conflicted.entries.length, 0);
    assert.equal(conflicted.conflicts.length, 1);
    assert.equal(conflicted.exportBlocked, true);
  });
});

test("rejects stale writes and never rewrites a foreign fragment", async () => {
  await temporaryWorkspace(async (root) => {
    const firstId = randomUUID();
    const secondId = randomUUID();
    const first = await createWorkspace(root, firstId, DEFAULT_WORKSPACE_PROFILE);
    const second = await joinWorkspace(root, secondId);
    const firstBefore = await readFile(first.localFragmentPath, "utf8");
    const foreignBefore = await readFile(second.localFragmentPath, "utf8");
    await saveLocalEntries(root, secondId, second.revision, [{
      uid: randomUUID(), commandId: "acronym", values: { short: "DVL", long: "log" },
    }]);
    assert.equal(await readFile(first.localFragmentPath, "utf8"), firstBefore);
    assert.notEqual(await readFile(second.localFragmentPath, "utf8"), foreignBefore);
    await assert.rejects(
      saveLocalEntries(root, firstId, first.revision, []),
      WorkspaceConflictError,
    );
  });
});

test("rejects an invalid manifest marker and duplicate installation identity", async () => {
  await temporaryWorkspace(async (root) => {
    const installationId = randomUUID();
    const workspace = await createWorkspace(root, installationId, DEFAULT_WORKSPACE_PROFILE, "Peter");
    const manifestPath = path.join(root, ".tacroman-workspace.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as Record<string, unknown>;
    manifest.format = "not-tacroman";
    await writeFile(manifestPath, JSON.stringify(manifest), "utf8");
    await assert.rejects(loadWorkspace(root, installationId), WorkspaceError);

    manifest.format = "tacroman-workspace";
    await writeFile(manifestPath, JSON.stringify(manifest), "utf8");
    const duplicate = JSON.parse(await readFile(workspace.localFragmentPath, "utf8")) as {
      owner: { suffix: string };
    };
    duplicate.owner.suffix = "Ab12Cd34";
    await writeFile(path.join(root, "Peter_Ab12Cd34.tacroman.json"), JSON.stringify(duplicate), "utf8");
    await assert.rejects(loadWorkspace(root, installationId), WorkspaceError);
  });
});

test("matches the shared Python/TypeScript workspace contract fixture", async () => {
  const fixturePath = path.resolve(__dirname, "..", "..", "..", "tests", "fixtures", "workspace_contract.json");
  const fixture = JSON.parse(await readFile(fixturePath, "utf8")) as {
    manifest: unknown;
    fragments: Record<string, unknown>;
    expected: { merged_keys: string[]; conflict_labels: string[]; conflict_ids: string[] };
  };
  await temporaryWorkspace(async (root) => {
    await writeFile(path.join(root, ".tacroman-workspace.json"), JSON.stringify(fixture.manifest), "utf8");
    for (const [name, payload] of Object.entries(fixture.fragments)) {
      await writeFile(path.join(root, name), JSON.stringify(payload), "utf8");
    }
    const snapshot = await loadWorkspace(root, "22222222-2222-4222-8222-222222222222");
    assert.deepEqual(snapshot.entries.map((entry) => entry.values.short), fixture.expected.merged_keys);
    assert.deepEqual(snapshot.conflicts.map((conflict) => conflict.label), fixture.expected.conflict_labels);
    assert.deepEqual(snapshot.conflicts.map((conflict) => conflict.id), fixture.expected.conflict_ids);
  });
});
