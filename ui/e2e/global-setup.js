import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/* Writes the mock datasets and their expected values before the suite runs. The expected values are generated from
   the backend stress tests' answer key each run rather than kept in git - see tests/stress/make_e2e_expected.py. */

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

export default function globalSetup() {
    execFileSync(path.join(".venv", "bin", "python"), ["-m", "tests.stress.make_e2e_expected"], {
        cwd: REPO_ROOT,
        stdio: "inherit",
    });
}
