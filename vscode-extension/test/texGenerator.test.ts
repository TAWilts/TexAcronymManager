import assert from "node:assert/strict";
import test from "node:test";
import { renderGeneratedOutput } from "../src/texGenerator";

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
