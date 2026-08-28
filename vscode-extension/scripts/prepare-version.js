#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const extensionDir = path.resolve(__dirname, '..');
const versionFile = path.join(extensionDir, 'VERSION');
const packageFile = path.join(extensionDir, 'package.json');
const packageLockFile = path.join(extensionDir, 'package-lock.json');

function writeIfChanged(file, content) {
  if (!fs.existsSync(file) || fs.readFileSync(file, 'utf8') !== content) {
    fs.writeFileSync(file, content);
  }
}

function readRequestedVersion() {
  if (!fs.existsSync(versionFile)) {
    throw new Error(`Version file not found: ${versionFile}`);
  }

  const version = fs.readFileSync(versionFile, 'utf8').trim();
  if (!/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error('VERSION must contain a release version in major.minor.patch format, for example 0.6.9.');
  }
  return version;
}

function incrementPatch(version) {
  const [major, minor, patch] = version.split('.').map(Number);
  return `${major}.${minor}.${patch + 1}`;
}

function findAvailableVersion(requestedVersion, packageName) {
  let version = requestedVersion;
  while (fs.existsSync(path.join(extensionDir, `${packageName}-${version}.vsix`))) {
    version = incrementPatch(version);
  }
  return version;
}

try {
  const requestedVersion = readRequestedVersion();
  const packageJson = JSON.parse(fs.readFileSync(packageFile, 'utf8'));
  const version = findAvailableVersion(requestedVersion, packageJson.name);

  packageJson.version = version;
  writeIfChanged(packageFile, `${JSON.stringify(packageJson, null, 2)}\n`);
  writeIfChanged(versionFile, `${version}\n`);

  if (fs.existsSync(packageLockFile)) {
    const packageLock = JSON.parse(fs.readFileSync(packageLockFile, 'utf8'));
    if (packageLock.packages?.['']) {
      packageLock.packages[''].version = version;
      writeIfChanged(packageLockFile, `${JSON.stringify(packageLock, null, 2)}\n`);
    }
  }

  if (version === requestedVersion) {
    console.log(`Packaging version ${version}.`);
  } else {
    console.log(`VSIX for ${requestedVersion} already exists; using next available version ${version}.`);
  }
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
