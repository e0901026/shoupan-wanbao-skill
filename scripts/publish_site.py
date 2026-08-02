from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from build_site import build_site


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def publish_site(
    repo: str | Path,
    output_dir: str | Path = "output",
    site_dir: str | Path = "site",
    push: bool = False,
) -> dict[str, object]:
    root = Path(repo).resolve()
    output = root / output_dir
    site = root / site_dir
    manifest = build_site(output, site, generate_pdfs=True)
    result: dict[str, object] = {"manifest": manifest, "committed": False, "pushed": False}
    if not push:
        return result

    staged_before = [line for line in git_output(root, "diff", "--cached", "--name-only").splitlines() if line]
    unrelated_staged = [name for name in staged_before if not (name == str(site_dir) or name.startswith(f"{site_dir}/"))]
    if unrelated_staged:
        raise RuntimeError(f"存在与站点无关的已暂存文件，拒绝自动提交：{', '.join(unrelated_staged)}")

    git_output(root, "add", "--", str(site_dir))
    staged_site = git_output(root, "diff", "--cached", "--name-only", "--", str(site_dir))
    if not staged_site:
        return result

    message = f"Update report site {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    git_output(root, "commit", "-m", message, "--", str(site_dir))
    result["committed"] = True
    branch = git_output(root, "branch", "--show-current") or "main"
    git_output(root, "push", "origin", branch)
    result["pushed"] = True
    pages_sha = git_output(root, "subtree", "split", "--prefix", str(site_dir))
    git_output(root, "push", "origin", f"{pages_sha}:refs/heads/gh-pages")
    result["pages_branch_pushed"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and optionally push the GitHub Pages report site.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            publish_site(args.repo, args.output_dir, args.site_dir, push=args.push),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
