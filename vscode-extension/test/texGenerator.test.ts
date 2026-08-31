import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { generateWorkspaceOutput, renderGeneratedOutput } from "../src/texGenerator";
import { DEFAULT_WORKSPACE_PROFILE } from "../src/workspace";

test("generates TeX whenever a v2 acronym database changes", () => {
  const output = renderGeneratedOutput({
    schema_version: 2,
    entries: [
      { command_id: "acronym", values: { short: "DVL", long: "Doppler velocity log" } },
      { command_id: "acronym", values: { short: "AUV", long: "autonomous underwater vehicle" } },
      { command_id: "acroplural", values: { key: "AUV", short_plural: "AUVs", long_plural: "autonomous underwater vehicles" } },
    ],
  });

  assert.equal(
    output,
    "\\begin{acronym}\n"
      + "\\acro{AUV}{autonomous underwater vehicle}\n"
      + "\\acro{DVL}{Doppler velocity log}\n"
      + "\\acroplural{AUV}[AUVs]{autonomous underwater vehicles}"
      + "\n\\end{acronym}\n",
  );
});

test("uses the render profile published by the desktop app", () => {
  const output = renderGeneratedOutput(
    { entries: [{ command_id: "acronym", values: { short: "A&B", long: "alpha_beta" } }] },
    {
      header: "",
      footer: "\n",
      separator: "\n",
      escape_mode: "latex",
      commands: [{
        id: "acronym",
        template: "\\newacronym{[[id]]}{[[short]]}{[[long]]}",
        fields: [{ id: "short" }, { id: "long" }],
      }],
    },
  );
  assert.equal(output, "\\newacronym{a\\_b}{A\\&B}{alpha\\_beta}\n");
});

test("does not rewrite identical workspace output", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "tacroman-output-"));
  try {
    const output = path.join(root, "entries.tex");
    const entries = [{ uid: "auv", commandId: "acronym", values: { short: "AUV", long: "vehicle" } }];
    assert.equal(await generateWorkspaceOutput(entries, output, DEFAULT_WORKSPACE_PROFILE), true);
    assert.equal(await generateWorkspaceOutput(entries, output, DEFAULT_WORKSPACE_PROFILE), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
