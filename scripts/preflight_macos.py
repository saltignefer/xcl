#!/usr/bin/env python3
"""Deterministic macOS cross-build, hygiene gate, and GPU suite runner for XCL.

Encodes repository invariants (privacy, no game data, base freshness, skip counting,
and regression comparison) so agents verify changes against real Metal execution via
CrossOver + vkd3d-proton 3.1 + KosmicKrisp instead of proxies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_EXTS = {".xvd", ".xvc", ".rpf", ".spv", ".dxil", ".cso", ".exe", ".dll", ".pdb"}
PRIVACY_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|proton|icloud|outlook|hotmail|yahoo)\.[A-Za-z]{2,}", re.I),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"C:\\\\Users\\\\[A-Za-z0-9._-]+\\\\", re.I),
]


def run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None,
        timeout: int = 600, check: bool = False) -> tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{p.stdout[-2000:]}")
    return p.returncode, p.stdout


def check_hygiene(base: str, ci: bool = False) -> list[str]:
    errors: list[str] = []

    # 1. Author identity check (local git config locally; commit log in CI)
    if ci:
        rc, log_out = run(["git", "log", f"{base}..HEAD", "--format=%an <%ae>"], cwd=ROOT)
        if rc == 0:
            for line in log_out.splitlines():
                if not line.strip():
                    continue
                if re.search(r"@(?:gmail|proton|icloud|outlook|hotmail|yahoo)\.", line, re.I):
                    errors.append(f"personal email in commit history: {line}")
    else:
        _, name = run(["git", "config", "user.name"], cwd=ROOT)
        _, email = run(["git", "config", "user.email"], cwd=ROOT)
        if name.strip() != "saltis" or not email.strip().endswith("@users.noreply.github.com"):
            errors.append(f"git identity must be saltis <*@users.noreply.github.com>, got: {name.strip()} <{email.strip()}>")

    # 2. Base freshness check (prevents stale-base batch-merge failures)
    rc, behind_out = run(["git", "rev-list", "--count", f"HEAD..{base}"], cwd=ROOT)
    if rc == 0:
        behind = int(behind_out.strip() or "0")
        if behind > 25:
            errors.append(f"branch is {behind} commits behind {base}; rebase before opening a PR")

    # 3. Changed files check: forbidden binary/game-data extensions + privacy patterns + monolith contention
    rc, files_out = run(["git", "diff", "--name-only", base], cwd=ROOT)
    changed = [f for f in files_out.splitlines() if f.strip()] if rc == 0 else []
    _, untracked_out = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT)
    changed += [f for f in untracked_out.splitlines() if f.strip()]
    changed_set = sorted(set(changed))

    has_code = any(f.startswith("crates/") for f in changed_set)
    if has_code:
        for f in changed_set:
            if f == "HANDOFF.md" or f.startswith("docs/specs/"):
                errors.append(f"code change also edits monolith doc {f}; note doc updates in the PR body instead")

    for rel in changed_set:
        p = ROOT / rel
        if p.suffix.lower() in FORBIDDEN_EXTS:
            errors.append(f"forbidden file extension in diff: {rel}")
            continue
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in PRIVACY_PATTERNS:
            if rel == "scripts/preflight_macos.py":
                continue
            m = pat.search(text)
            if m:
                errors.append(f"privacy/local-path pattern {pat.pattern!r} matched in {rel}: {m.group(0)!r}")

    # 4. Check added #[ignore] in GPU tests (prevents silent test weakening)
    rc, diff_out = run(["git", "diff", base, "--", "crates/"], cwd=ROOT)
    if rc == 0:
        for line in diff_out.splitlines():
            if line.startswith("+") and not line.startswith("+++") and "#[ignore" in line:
                errors.append(f"new #[ignore] added in crates/: {line.strip()}")

    return errors


def build_xcl(tools_dir: Path) -> Path:
    _, sysroot = run(["rustc", "--print", "sysroot"], check=True)
    rust_lld = Path(sysroot.strip()) / "lib/rustlib/aarch64-apple-darwin/bin/rust-lld"
    env = os.environ.copy()
    env.update({
        "CC_x86_64_pc_windows_msvc": "/opt/homebrew/opt/llvm/bin/clang-cl",
        "AR_x86_64_pc_windows_msvc": "/opt/homebrew/opt/llvm/bin/llvm-lib",
        "CFLAGS_x86_64_pc_windows_msvc": (
            f"-FIstring.h -imsvc{tools_dir}/msvc-inc "
            f"-imsvc{tools_dir}/winsdk-inc/ucrt "
            f"-imsvc{tools_dir}/winsdk-inc/um "
            f"-imsvc{tools_dir}/winsdk-inc/shared"
        ),
        "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER": str(rust_lld),
        "RUSTFLAGS": (
            f"-L native={tools_dir}/msvc-lib "
            f"-L native={tools_dir}/winsdk-lib/ucrt/x64 "
            f"-L native={tools_dir}/winsdk-lib/um/x64"
        ),
    })
    t0 = time.time()
    rc, out = run(
        ["cargo", "test", "--no-run", "-p", "xcl", "--lib", "--target", "x86_64-pc-windows-msvc"],
        cwd=ROOT,
        env=env,
        timeout=600,
    )
    if rc != 0:
        print(out[-4000:], file=sys.stderr)
        raise SystemExit(rc)
    deps = ROOT / "target/x86_64-pc-windows-msvc/debug/deps"
    exes = sorted(deps.glob("xcl-*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not exes:
        raise RuntimeError(f"No xcl-*.exe found in {deps}")
    print(f"build ok in {time.time() - t0:.1f}s: {exes[0].name}", flush=True)
    return exes[0]


def run_gpu_suite(exe: Path, tools_dir: Path, bottle: str, filt: str,
                  disable_cache: bool, extra_tests: list[str]) -> dict:
    cxbin = Path(os.environ.get(
        "CROSSOVER_BIN",
        "/Applications/CrossOver Preview.app/Contents/SharedSupport/CrossOver/bin",
    ))
    dxc = tools_dir / "dxc/unpacked/bin/x64"
    env = os.environ.copy()
    env.update({
        "KK_SHIM_VKD3D_COMPAT": "1",
        "VKD3D_FEATURE_LEVEL": "12_1",
        "VKD3D_SHADER_MODEL": "6_6",
        "VKD3D_DEBUG": "err",
        "VKD3D_SHADER_CACHE_PATH": "Z:/tmp/xcl-vkd3d-cache",
        "XCL_DXC_DIR": f"Z:{dxc}",
    })
    if disable_cache:
        env["MESA_SHADER_CACHE_DISABLE"] = "1"
        env["VKD3D_SHADER_CACHE_PATH"] = "0"

    def wine(args: list[str], timeout: int = 240) -> tuple[int, str]:
        return run([str(cxbin / "wine"), "--bottle", bottle, str(exe)] + args, env=env, timeout=timeout)

    if extra_tests:
        tests = extra_tests
    else:
        _, listing = wine(["--list"], timeout=60)
        pat = re.compile(rf"^(\S*{re.escape(filt)}\S*): test$")
        tests = []
        for line in listing.splitlines():
            m = pat.match(line.strip())
            if m:
                tests.append(m.group(1))

    print(f"running {len(tests)} tests in bottle={bottle}", flush=True)
    results: dict[str, dict[str, str]] = {}
    batch_size = 16 if not extra_tests else len(tests)
    chunks = [tests[i:i + batch_size] for i in range(0, len(tests), batch_size)]

    for chunk in chunks:
        remaining = list(chunk)
        while remaining:
            args = ["--test-threads=1", "--nocapture", "--exact"] + remaining
            try:
                rc, out = wine(args, timeout=180)
            except subprocess.TimeoutExpired as exc:
                rc = -999
                out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                subprocess.run(["pkill", "-9", "-f", exe.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            seen: list[str] = []
            cur: str | None = None
            cur_lines: list[str] = []
            for raw in out.splitlines():
                line = raw.replace("\r", "")
                m = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", line)
                if m:
                    name, st = m.group(1), m.group(2)
                    results[name] = {"status": st, "detail": ""}
                    seen.append(name)
                    cur = None
                    continue
                m2 = re.match(r"^test (\S+) \.\.\.(.*)$", line)
                if m2:
                    cur = m2.group(1)
                    cur_lines = [m2.group(2).strip()] if m2.group(2).strip() else []
                    continue
                if cur:
                    if line.strip() in ("ok", "FAILED", "ignored"):
                        st = line.strip()
                        if st == "ok" and any("SKIPPED " in l for l in cur_lines):
                            st = "SKIPPED"
                        results[cur] = {"status": st, "detail": "\n".join(cur_lines[-8:])}
                        seen.append(cur)
                        cur = None
                    else:
                        cur_lines.append(line)

            finished = set(seen)
            if cur and cur not in finished:
                st = "TIMEOUT" if rc == -999 else "ABORT"
                results[cur] = {"status": st, "detail": f"rc={rc}\n" + "\n".join(cur_lines[-10:])}
                finished.add(cur)
                print(f"  {st}: {cur}", flush=True)
            elif not seen and remaining:
                bad = remaining[0]
                results[bad] = {"status": "ABORT", "detail": f"early rc={rc}\n{out[-400:]}"}
                finished.add(bad)
                print(f"  EARLY ABORT: {bad}", flush=True)

            remaining = [t for t in remaining if t not in finished]

    # Retry tests that timed out inside a multi-test chunk in an isolated process
    # (process-wide D3D12/UMA singletons from an earlier test in the chunk can stall a later one).
    if batch_size > 1:
        timed_out = [t for t, v in results.items() if v["status"] == "TIMEOUT"]
        for t in timed_out:
            print(f"  retrying in isolated process: {t}", flush=True)
            try:
                rc, out = wine(["--test-threads=1", "--nocapture", "--exact", t], timeout=90)
            except subprocess.TimeoutExpired:
                subprocess.run(["pkill", "-9", "-f", exe.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                continue
            for raw in out.splitlines():
                line = raw.replace("\r", "")
                m = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", line)
                if m and m.group(1) == t:
                    st = m.group(2)
                    if st == "ok" and "SKIPPED " in out:
                        st = "SKIPPED"
                    results[t] = {"status": st, "detail": "isolated retry"}
                    break

    counts: dict[str, int] = {}
    for v in results.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {"total": len(tests), "counts": counts, "tests": results}


def main() -> int:
    ap = argparse.ArgumentParser(description="XCL macOS preflight, cross-build, and GPU suite runner")
    ap.add_argument("--base", default="origin/main", help="Base ref for hygiene checks")
    ap.add_argument("--tools-dir", type=Path, default=ROOT.parent / "tools", help="Directory with msvc-inc/winsdk-inc/dxc")
    ap.add_argument("--bottle", default="xcl-kk", help="CrossOver bottle name")
    ap.add_argument("--check-hygiene", action="store_true", help="Run git/privacy/game-data hygiene checks")
    ap.add_argument("--ci", action="store_true", help="CI mode for --check-hygiene (audit commit log instead of local git config)")
    ap.add_argument("--build", action="store_true", help="Cross-compile xcl test binary")
    ap.add_argument("--suite", action="store_true", help="Run GPU test suite under CrossOver")
    ap.add_argument("--filter", default="::gpu_", help="Substring filter for --suite")
    ap.add_argument("--test", action="append", default=[], help="Exact test name(s) to run")
    ap.add_argument("--no-cache", action="store_true", help="Disable Mesa and vkd3d-proton shader caches")
    ap.add_argument("--out", type=Path, help="Write JSON report to path")
    ap.add_argument("--baseline", type=Path, help="Compare against baseline JSON and fail on regressions")
    args = ap.parse_args()

    if not (args.check_hygiene or args.build or args.suite or args.test):
        args.check_hygiene = True
        args.build = True

    if args.check_hygiene:
        errs = check_hygiene(args.base, ci=args.ci)
        if errs:
            print("HYGIENE FAILED:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print("hygiene ok", flush=True)

    exe: Path | None = None
    if args.build:
        exe = build_xcl(args.tools_dir)
    elif args.suite or args.test:
        deps = ROOT / "target/x86_64-pc-windows-msvc/debug/deps"
        exes = sorted(deps.glob("xcl-*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not exes:
            print("No built xcl-*.exe found; pass --build", file=sys.stderr)
            return 1
        exe = exes[0]

    if args.suite or args.test:
        assert exe is not None
        report = run_gpu_suite(exe, args.tools_dir, args.bottle, args.filter, args.no_cache, args.test)
        print(f"RESULT: total={report['total']} counts={report['counts']}")
        for name, info in sorted(report["tests"].items()):
            if info["status"] != "ok":
                first = next((l.strip() for l in info["detail"].splitlines() if l.strip()), "")
                print(f"  [{info['status']}] {name} :: {first[:110]}")
        if args.out:
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if args.baseline and args.baseline.is_file():
            base = json.loads(args.baseline.read_text(encoding="utf-8"))
            regressions = [
                t for t, b in base.get("tests", {}).items()
                if b.get("status") == "ok" and report["tests"].get(t, {}).get("status") != "ok"
            ]
            if regressions:
                print(f"REGRESSIONS vs {args.baseline}: {len(regressions)}", file=sys.stderr)
                for r in regressions:
                    print(f"  - {r} -> {report['tests'].get(r, {}).get('status')}", file=sys.stderr)
                return 2
        if report["counts"].get("FAILED", 0) or report["counts"].get("ABORT", 0) or report["counts"].get("TIMEOUT", 0):
            return 1 if args.test else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
