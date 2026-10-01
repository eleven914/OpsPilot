import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { createServer } from "vite";

const webPort = Number(process.env.OPSPILOT_E2E_WEB_PORT ?? "5174");

async function waitForHealth(url: string): Promise<void> {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The API process is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 200));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

export default async function globalSetup() {
  const projectRoot = resolve(import.meta.dirname, "../../..");
  const apiProcess = spawn("python", [resolve(projectRoot, "scripts/start_e2e_api.py")], {
    cwd: projectRoot,
    env: process.env,
    stdio: "inherit"
  });
  await waitForHealth("http://127.0.0.1:8010/health");

  process.env.VITE_API_PROXY = "http://127.0.0.1:8010";
  const vite = await createServer({
    configFile: resolve(projectRoot, "apps/web/vite.config.ts"),
    root: resolve(projectRoot, "apps/web"),
    server: { host: "127.0.0.1", port: webPort, strictPort: true }
  });
  await vite.listen();

  return async () => {
    try {
      await fetch("http://127.0.0.1:8010/__e2e_shutdown", { method: "POST" });
    } finally {
      await vite.close();
      // The test server exits itself shortly after acknowledging shutdown.
      // Killing the same Windows process handle during exit can crash Node/libuv.
      if (apiProcess.exitCode === null) {
        await new Promise<void>((resolveExit) => {
          const timer = setTimeout(() => {
            apiProcess.kill();
            resolveExit();
          }, 5_000);
          apiProcess.once("exit", () => {
            clearTimeout(timer);
            resolveExit();
          });
        });
      }
    }
  };
}
