"""Fail publication for local state, credential patterns, broken local doc links or version drift."""
import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", ".build", "dist", "__pycache__"}
FORBIDDEN = {"profiles", "engine", "test-reviews", "backups", "incidents"}


def audit(root=ROOT):
    errors = []
    count = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if SKIP.intersection(relative.parts) or not path.is_file():
            continue
        count += 1
        if (FORBIDDEN.intersection(relative.parts) or path.suffix in {".sqlite", ".db", ".log", ".exe", ".pem", ".key"}
                or path.name in {"settings.json", "update-state.json", ".env"}):
            errors.append(f"Local state/credential/build artifact: {relative}")
        if path.suffix.lower() in {".png", ".jpg", ".ico"}:
            continue
        text = path.read_text("utf-8-sig")
        if re.search(r"[A-Z]:[\\/]Users[\\/][^\\/\s]+", text, re.I):
            errors.append(f"Machine-specific user path: {relative}")
        if re.search(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-proj-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)", text):
            errors.append(f"Potential credential: {relative}")
        if path.suffix in {".py", ".cs", ".ps1"} and path.name != "audit_publication.py":
            if re.search(r"Koppel|Stepan|eternalchill|NeonFraction", text, re.I):
                errors.append(f"Non-synthetic personal fixture/default: {relative}")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in target and not target.startswith("#") and not (path.parent / target.split("#")[0]).exists():
                    errors.append(f"Broken local link in {relative}: {target}")
    tree = ast.parse((root / "runtime.py").read_text("utf-8-sig"))
    version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    if f'const string Release = "{version}"' not in (root / "Setup.cs").read_text():
        errors.append("Setup.cs version mismatch")
    if f"FabWatchSetup-{version}-x64.exe" not in (root / "build.ps1").read_text():
        errors.append("build.ps1 version mismatch")
    if not (root / "docs" / "releases" / f"{version}.md").exists():
        errors.append("Missing release notes")
    for error in errors:
        print(error)
    print(f"Audited {count} source/docs/assets; {len(errors)} issue(s).")
    return not errors


if __name__ == "__main__":
    sys.exit(0 if audit() else 1)
