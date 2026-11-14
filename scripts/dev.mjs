import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const candidates = process.platform === "win32"
  ? [resolve(root, ".venv/Scripts/python.exe"), resolve(root, "../.venv/Scripts/python.exe")]
  : [resolve(root, ".venv/bin/python"), resolve(root, "../.venv/bin/python")];
const python = process.env.PYTHON || candidates.find(existsSync) || (process.platform === "win32" ? null : "python3");
if (!python) {
  console.error("Native Python environment missing. Create .venv using Windows Python 3.12, or set PYTHON to its executable.");
  process.exit(1);
}
const args = process.argv.slice(2).filter(arg => arg !== "--strictPort");
if (!args.includes("--port")) args.push("--port", "8000");
if (!args.includes("--host")) args.push("--host", "127.0.0.1");
const child = spawn(python, ["-m", "uvicorn", "touchline.api:app", ...args], {stdio:"inherit", cwd:root});
child.on("error", error => { console.error(error.message); process.exitCode = 1; });
for (const signal of ["SIGINT","SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", code => process.exit(code ?? 1));
