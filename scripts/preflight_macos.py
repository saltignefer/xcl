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
PERSONAL_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:gmail|proton|protonmail|icloud|outlook|hotmail|yahoo|me|live|fastmail|hey)\.[A-Za-z]{2,}",
    re.I,
)
PRIVACY_PATTERNS = [
    ("personal-email", PERSONAL_EMAIL_RE),
    ("macos-home-path", re.compile(r"/Users/[A-Za-z0-9._-]+/")),
    ("windows-home-path", re.compile(r"C:[\\/]+Users[\\/]+[A-Za-z0-9._-]+[\\/]", re.I)),
]
IGNORE_ATTR_RE = re.compile(r"#\[\s*(?:ignore\b|cfg_attr\s*\(.*\bignore\b)")


def _has_ignore_attr(line: str) -> bool:
    code = line.split("//", 1)[0]
    return bool(IGNORE_ATTR_RE.search(code))


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


def check_hygiene(base: str, ci: bool = False, freshness_base: str | None = None) -> list[str]:
    errors: list[str] = []

    # 0. Base ref must resolve to a valid commit (never silently pass on bad refs)
    rc, base_sha_out = run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], cwd=ROOT)
    if rc != 0 or not base_sha_out.strip():
        return [f"invalid base ref: {base}"]
    base_sha = base_sha_out.strip()

    # 1. Local git config identity check (outside CI)
    if not ci:
        _, name = run(["git", "config", "user.name"], cwd=ROOT)
        _, email = run(["git", "config", "user.email"], cwd=ROOT)
        if name.strip() != "saltis" or not email.strip().endswith("@users.noreply.github.com"):
            errors.append(f"git identity must be saltis <*@users.noreply.github.com>, got: {name.strip()} <{email.strip()}>")

    # 2. Audit every commit introduced in base..HEAD (both locally and in CI):
    #    - author & committer email hygiene
    #    - commit message privacy check
    #    - per-commit diff/path scan (catches forbidden artifacts/PII added & removed mid-push)
    rc, log_out = run(
        ["git", "log", f"{base_sha}..HEAD", "--format=%H%x1f%P%x1f%an <%ae>%x1f%cn <%ce>%x1f%B%x1e"],
        cwd=ROOT,
    )
    commit_shas: list[str] = []
    if rc != 0:
        errors.append(f"git log failed for {base_sha}..HEAD: {log_out.strip()}")
    else:
        for rec in log_out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x1f", 4)
            if len(parts) < 5:
                continue
            sha, parents, author, committer, msg = parts
            commit_shas.append(sha)
            is_merge = len(parents.split()) > 1
            for role, ident in (("author", author), ("committer", committer)):
                if PERSONAL_EMAIL_RE.search(ident):
                    errors.append(f"personal email in commit {sha[:8]} ({role}) [redacted]")
                else:
                    ok_fork = bool(re.match(r"^saltis <[^<>]+@users\.noreply\.github\.com>$", ident))
                    ok_gh_committer = role == "committer" and ident == "GitHub <noreply@github.com>"
                    if not (ok_fork or ok_gh_committer):
                        errors.append(f"commit {sha[:8]} ({role}) does not use fork identity 'saltis <*@users.noreply.github.com>'")
            for label, pat in PRIVACY_PATTERNS:
                if pat.search(msg):
                    errors.append(f"privacy pattern ({label}) matched in commit message {sha[:8]} [redacted]")

    for sha in commit_shas:
        rc, ns_out = run(
            ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "-m", "--first-parent", sha],
            cwd=ROOT,
        )
        if rc != 0:
            errors.append(f"git diff-tree failed for {sha[:8]}: {ns_out.strip()}")
        else:
            for line in ns_out.splitlines():
                cols = line.split("\t")
                status = cols[0] if cols else ""
                if status.startswith("D"):
                    continue
                for rel in cols[1:]:
                    if Path(rel).suffix.lower() in FORBIDDEN_EXTS:
                        errors.append(f"forbidden file extension committed in {sha[:8]}: {rel}")
        rc, patch_out = run(["git", "show", "--format=", "--unified=0", "-m", "--first-parent", sha], cwd=ROOT)
        if rc != 0:
            errors.append(f"git show failed for {sha[:8]}: {patch_out.strip()}")
        else:
            cur_file = "<unknown>"
            for line in patch_out.splitlines():
                if line.startswith("+++ b/"):
                    cur_file = line[6:]
                elif line.startswith("+") and not line.startswith("+++"):
                    added = line[1:]
                    for label, pat in PRIVACY_PATTERNS:
                        if pat.search(added):
                            errors.append(f"privacy pattern ({label}) added in commit {sha[:8]} ({cur_file}) [redacted]")
                            break
                    if cur_file.startswith("crates/") and _has_ignore_attr(added):
                        errors.append(f"new ignore attribute added in {sha[:8]} ({cur_file}): {added.strip()}")

    # 3. Base freshness check (prevents stale-base batch-merge failures)
    fbase = freshness_base or base
    rc, fsha_out = run(["git", "rev-parse", "--verify", "--quiet", f"{fbase}^{{commit}}"], cwd=ROOT)
    if rc != 0 or not fsha_out.strip():
        errors.append(f"invalid freshness base ref: {fbase}")
    else:
        fsha = fsha_out.strip()
        rc, behind_out = run(["git", "rev-list", "--count", f"HEAD..{fsha}"], cwd=ROOT)
        if rc != 0:
            errors.append(f"git rev-list failed for HEAD..{fsha}: {behind_out.strip()}")
        else:
            behind = int(behind_out.strip() or "0")
            if behind > 25:
                errors.append(f"branch is {behind} commits behind {fbase}; rebase before opening a PR")

    # 4. Changed files check (net branch diff + uncommitted + untracked):
    #    - monolith doc mixing check
    #    - working tree & untracked forbidden extensions / privacy patterns
    changed: list[str] = []
    for diff_cmd in (
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base_sha}...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=d", "HEAD"],
    ):
        rc, files_out = run(diff_cmd, cwd=ROOT)
        if rc != 0:
            errors.append(f"{' '.join(diff_cmd)} failed: {files_out.strip()}")
        else:
            changed.extend(f for f in files_out.splitlines() if f.strip())
    rc, untracked_out = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT)
    if rc != 0:
        errors.append(f"git ls-files failed: {untracked_out.strip()}")
    else:
        changed.extend(f for f in untracked_out.splitlines() if f.strip())
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
        for label, pat in PRIVACY_PATTERNS:
            if pat.search(text):
                errors.append(f"privacy pattern ({label}) matched in {rel} [redacted]")

    # 5. Uncommitted diff ignore-attribute check in crates/
    rc, diff_out = run(["git", "diff", "HEAD", "--", "crates/"], cwd=ROOT)
    if rc != 0:
        errors.append(f"git diff HEAD -- crates/ failed: {diff_out.strip()}")
    else:
        for line in diff_out.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added = line[1:]
                if _has_ignore_attr(added):
                    errors.append(f"new ignore attribute added in working tree crates/: {added.strip()}")

    return errors


def _cargo_msvc_env(tools_dir: Path) -> dict[str, str]:
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
    return env


def build_xcl(tools_dir: Path, lib_only: bool = False) -> list[tuple[str, Path]]:
    env = _cargo_msvc_env(tools_dir)
    cmd = ["cargo", "test", "--no-run", "-p", "xcl", "--target", "x86_64-pc-windows-msvc", "--message-format=json"]
    if lib_only:
        cmd.append("--lib")
    t0 = time.time()
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=600,
    )
    if p.returncode != 0:
        if p.stderr:
            print(p.stderr[-4000:], file=sys.stderr)
        for line in p.stdout.splitlines():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("reason") == "compiler-message":
                rendered = msg.get("message", {}).get("rendered")
                if rendered:
                    print(rendered, file=sys.stderr)
        raise SystemExit(p.returncode)

    exes: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for line in p.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("reason") == "compiler-artifact" and msg.get("profile", {}).get("test"):
            exe_str = msg.get("executable")
            if exe_str:
                ep = Path(exe_str)
                if ep.is_file() and ep not in seen:
                    seen.add(ep)
                    tgt = msg.get("target", {})
                    kinds = tgt.get("kind", [])
                    label = "lib" if "lib" in kinds else tgt.get("name", ep.stem)
                    exes.append((label, ep))
    if not exes:
        raise RuntimeError("cargo test --no-run produced no test executables")
    names = ", ".join(e.name for _, e in exes)
    print(f"build ok in {time.time() - t0:.1f}s: {names}", flush=True)
    return exes


def _kill_bottle(cxbin: Path, bottle: str) -> None:
    wineserver = cxbin / "wineserver"
    prefix = Path.home() / "Library/Application Support/CrossOver/Bottles" / bottle
    if wineserver.is_file() and prefix.is_dir():
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix)
        for flag in ("-k9", "-w"):
            try:
                subprocess.run([str(wineserver), flag], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except subprocess.TimeoutExpired:
                pass


def _unwrap_wine_test_lines(out: str) -> list[str]:
    """Rejoin `test <long_name> ...` lines wrapped at 80 columns by Wine's console."""
    raw_lines = [raw.replace("\r", "") for raw in out.splitlines()]
    merged: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if line.startswith("test ") and " ..." not in line and not line.startswith("test result:"):
            buf = line
            j = i + 1
            while j < len(raw_lines) and " ..." not in buf and j - i < 4:
                nxt = raw_lines[j]
                if not nxt or nxt.startswith("test ") or nxt.startswith("running "):
                    break
                buf += nxt
                j += 1
            if " ..." in buf:
                merged.append(buf)
                i = j
                continue
        merged.append(line)
        i += 1
    return merged


def _has_skip_marker(test_name: str, lines: list[str]) -> bool:
    for line in lines:
        if f"SKIPPED {test_name}" in line:
            return True
        if re.search(r"(?:^|\s)SKIPPED(?::|\s)", line):
            # Reject lines that explicitly name a *different* test
            m = re.search(r"SKIPPED\s+([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)", line)
            if m and "::" in m.group(1) and m.group(1) != test_name:
                continue
            return True
    return False


def run_gpu_suite(exes: list[tuple[str, Path]], tools_dir: Path, bottle: str, filt: str,
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

    def wine(exe: Path, args: list[str], timeout: int = 240) -> tuple[int, str]:
        return run([str(cxbin / "wine"), "--bottle", bottle, str(exe)] + args, env=env, timeout=timeout)

    # Discover tests per executable via `--list` (fail fast on discovery errors)
    plan: list[tuple[str, Path, list[str]]] = []
    if extra_tests:
        remaining_extra = set(extra_tests)
        for label, exe in exes:
            rc, listing = wine(exe, ["--list"], timeout=60)
            if rc != 0:
                raise RuntimeError(f"test discovery failed for {exe.name} (rc={rc}):\n{listing[-1000:]}")
            available = {
                m.group(1)
                for line in listing.splitlines()
                if (m := re.match(r"^(\S+): test$", line.strip()))
            }
            matched = [t for t in extra_tests if t in available]
            if matched:
                plan.append((label, exe, matched))
                remaining_extra.difference_update(matched)
        if remaining_extra:
            raise RuntimeError(f"requested --test not found in any test binary: {sorted(remaining_extra)}")
    else:
        pat = re.compile(rf"^(\S*{re.escape(filt)}\S*): test$")
        for label, exe in exes:
            rc, listing = wine(exe, ["--list"], timeout=60)
            if rc != 0:
                raise RuntimeError(f"test discovery failed for {exe.name} (rc={rc}):\n{listing[-1000:]}")
            matched = [
                m.group(1)
                for line in listing.splitlines()
                if (m := pat.match(line.strip()))
            ]
            if matched:
                plan.append((label, exe, matched))

    total_tests = sum(len(ts) for _, _, ts in plan)
    if total_tests == 0:
        raise RuntimeError(f"0 tests discovered matching filter {filt!r} across {[e.name for _, e in exes]}")

    print(f"running {total_tests} tests across {len(plan)} binary(ies) in bottle={bottle}", flush=True)
    results: dict[str, dict[str, str]] = {}

    for label, exe, tests in plan:
        def key_for(name: str) -> str:
            return name if label == "lib" else f"{label}::{name}"

        batch_size = 16 if not extra_tests else len(tests)
        chunks = [tests[i:i + batch_size] for i in range(0, len(tests), batch_size)]

        for chunk in chunks:
            remaining = list(chunk)
            while remaining:
                args = ["--test-threads=1", "--nocapture", "--exact"] + remaining
                try:
                    rc, out = wine(exe, args, timeout=180)
                except subprocess.TimeoutExpired as exc:
                    rc = -999
                    out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                    _kill_bottle(cxbin, bottle)

                seen: list[str] = []
                cur: str | None = None
                cur_lines: list[str] = []
                pre_lines: list[str] = []
                for line in _unwrap_wine_test_lines(out):
                    m = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", line)
                    if m:
                        name, st = m.group(1), m.group(2)
                        combined = pre_lines + (cur_lines if cur == name else [])
                        if st == "ok" and _has_skip_marker(name, combined):
                            st = "SKIPPED"
                        results[key_for(name)] = {"status": st, "detail": "\n".join(combined[-8:]) if st != "ok" else ""}
                        seen.append(name)
                        cur = None
                        cur_lines = []
                        pre_lines = []
                        continue
                    m2 = re.match(r"^test (\S+) \.\.\.(.*)$", line)
                    if m2:
                        cur = m2.group(1)
                        cur_lines = [m2.group(2).strip()] if m2.group(2).strip() else []
                        continue
                    if cur:
                        if line.strip() in ("ok", "FAILED", "ignored"):
                            st = line.strip()
                            combined = pre_lines + cur_lines
                            if st == "ok" and _has_skip_marker(cur, combined):
                                st = "SKIPPED"
                            results[key_for(cur)] = {"status": st, "detail": "\n".join(combined[-8:])}
                            seen.append(cur)
                            cur = None
                            cur_lines = []
                            pre_lines = []
                        else:
                            cur_lines.append(line)
                    else:
                        if line.strip():
                            pre_lines.append(line)
                            if len(pre_lines) > 16:
                                pre_lines.pop(0)

                finished = set(seen)
                if cur and cur not in finished:
                    st = "TIMEOUT" if rc == -999 else "ABORT"
                    results[key_for(cur)] = {"status": st, "detail": f"rc={rc}\n" + "\n".join(cur_lines[-10:])}
                    finished.add(cur)
                    print(f"  {st}: {key_for(cur)}", flush=True)
                elif not seen and remaining:
                    bad = remaining[0]
                    st = "TIMEOUT" if rc == -999 else "ABORT"
                    results[key_for(bad)] = {"status": st, "detail": f"early rc={rc}\n{out[-400:]}"}
                    finished.add(bad)
                    print(f"  EARLY {st}: {key_for(bad)}", flush=True)

                remaining = [t for t in remaining if t not in finished]

        # Retry tests that timed out inside a multi-test chunk in an isolated process
        if batch_size > 1:
            timed_out = [t for t in tests if results.get(key_for(t), {}).get("status") == "TIMEOUT"]
            for t in timed_out:
                print(f"  retrying in isolated process: {key_for(t)}", flush=True)
                try:
                    rc, out = wine(exe, ["--test-threads=1", "--nocapture", "--exact", t], timeout=90)
                except subprocess.TimeoutExpired:
                    _kill_bottle(cxbin, bottle)
                    continue
                lines = _unwrap_wine_test_lines(out)
                matched_st: str | None = None
                in_test = False
                for line in lines:
                    m = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", line)
                    if m and m.group(1) == t:
                        matched_st = m.group(2)
                        break
                    m2 = re.match(r"^test (\S+) \.\.\.(.*)$", line)
                    if m2 and m2.group(1) == t:
                        in_test = True
                        continue
                    if in_test and line.strip() in ("ok", "FAILED", "ignored"):
                        matched_st = line.strip()
                        break
                if matched_st is None and rc == 0 and re.search(r"test result:\s*ok\.\s*1 passed", out):
                    matched_st = "ok"
                if matched_st is not None:
                    if matched_st == "ok" and _has_skip_marker(t, lines):
                        matched_st = "SKIPPED"
                    results[key_for(t)] = {"status": matched_st, "detail": "isolated retry"}

    if len(results) != total_tests:
        raise RuntimeError(f"recorded {len(results)} results for {total_tests} planned tests")
    counts: dict[str, int] = {}
    for v in results.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {"total": total_tests, "counts": counts, "tests": results}


def _default_tools_dir() -> Path:
    ws_tools = ROOT.parent / "xcl-ws/tools"
    return ws_tools if ws_tools.is_dir() else ROOT.parent / "tools"


def main() -> int:
    ap = argparse.ArgumentParser(description="XCL macOS preflight, cross-build, and GPU suite runner")
    ap.add_argument("--base", default="origin/main", help="Base ref for hygiene checks")
    ap.add_argument("--freshness-base", default=None, help="Base ref for branch-staleness check (defaults to --base)")
    ap.add_argument("--tools-dir", type=Path, default=_default_tools_dir(), help="Directory with msvc-inc/winsdk-inc/dxc")
    ap.add_argument("--bottle", default="xcl-kk", help="CrossOver bottle name")
    ap.add_argument("--check-hygiene", action="store_true", help="Run git/privacy/game-data hygiene checks")
    ap.add_argument("--ci", action="store_true", help="CI mode for --check-hygiene (audit commit log instead of local git config)")
    ap.add_argument("--build", action="store_true", help="Cross-compile xcl test binaries")
    ap.add_argument("--lib-only", action="store_true", help="Only build/run --lib test binary")
    ap.add_argument("--suite", action="store_true", help="Run GPU test suite under CrossOver")
    ap.add_argument("--filter", default="gpu_", help="Substring filter for --suite")
    ap.add_argument("--test", action="append", default=[], help="Exact test name(s) to run")
    ap.add_argument("--no-cache", action="store_true", help="Disable Mesa and vkd3d-proton shader caches")
    ap.add_argument("--out", type=Path, help="Write JSON report to path")
    ap.add_argument("--baseline", type=Path, help="Compare against baseline JSON and fail on regressions")
    args = ap.parse_args()

    if not (args.check_hygiene or args.build or args.suite or args.test):
        args.check_hygiene = True
        args.build = True

    if args.baseline and not args.baseline.is_file():
        print(f"BASELINE MISSING: {args.baseline}", file=sys.stderr)
        return 2
    if args.baseline and args.out and (
        args.baseline.resolve() == args.out.resolve()
        or (args.out.exists() and args.baseline.samefile(args.out))
    ):
        print(f"REFUSING TO OVERWRITE BASELINE: --out and --baseline point to the same file ({args.out})", file=sys.stderr)
        return 2

    if args.check_hygiene:
        errs = check_hygiene(args.base, ci=args.ci, freshness_base=args.freshness_base)
        if errs:
            print("HYGIENE FAILED:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print("hygiene ok", flush=True)

    exes: list[tuple[str, Path]] = []
    if args.build:
        exes = build_xcl(args.tools_dir, lib_only=args.lib_only)
    elif args.suite or args.test:
        # Resolve exact current test artifacts via Cargo (fast no-op when already built)
        exes = build_xcl(args.tools_dir, lib_only=args.lib_only)

    if args.suite or args.test:
        try:
            report = run_gpu_suite(exes, args.tools_dir, args.bottle, args.filter, args.no_cache, args.test)
        except RuntimeError as exc:
            print(f"SUITE ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"RESULT: total={report['total']} counts={report['counts']}")
        for name, info in sorted(report["tests"].items()):
            if info["status"] != "ok":
                first = next((l.strip() for l in info["detail"].splitlines() if l.strip()), "")
                print(f"  [{info['status']}] {name} :: {first[:110]}")
        base_data = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
        if args.out:
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if base_data is not None:
            base_tests = base_data.get("tests", {})
            regressions = [
                t for t, b in base_tests.items()
                if b.get("status") == "ok" and report["tests"].get(t, {}).get("status") != "ok"
            ]
            new_failures = [
                t for t, cur in report["tests"].items()
                if cur.get("status") == "FAILED" and base_tests.get(t, {}).get("status") != "FAILED"
            ]
            if regressions or new_failures:
                if regressions:
                    print(f"REGRESSIONS vs {args.baseline}: {len(regressions)}", file=sys.stderr)
                    for r in regressions:
                        print(f"  - {r} -> {report['tests'].get(r, {}).get('status')}", file=sys.stderr)
                if new_failures:
                    print(f"NEW FAILURES not in {args.baseline}: {len(new_failures)}", file=sys.stderr)
                    for nf in new_failures:
                        print(f"  - {nf} -> FAILED", file=sys.stderr)
                return 2
            if report["counts"].get("ABORT", 0) or report["counts"].get("TIMEOUT", 0):
                return 1
            return 0
        if report["counts"].get("FAILED", 0) or report["counts"].get("ABORT", 0) or report["counts"].get("TIMEOUT", 0):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
