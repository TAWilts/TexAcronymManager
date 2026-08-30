const { copyFileSync, mkdirSync } = require("node:fs");
const path = require("node:path");

const repository = path.resolve(__dirname, "..", "..");
const source = path.join(repository, "src", "tacroman", "web_ui");
const target = path.join(repository, "vscode-extension", "assets", "webview");

mkdirSync(target, { recursive: true });
for (const filename of ["app.css", "app.js", "index.html"]) {
  copyFileSync(path.join(source, filename), path.join(target, filename));
}
copyFileSync(
  path.join(repository, "src", "tacroman", "defaults", "profiles.json"),
  path.join(target, "default-profiles.json"),
);
