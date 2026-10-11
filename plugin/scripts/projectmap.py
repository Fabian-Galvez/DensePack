"""Project map for the DensePack 2.0 start. DensePack 1.3.4 told the agent which files a folder holds when a message
named that folder. This map does the same for the whole project, once, at session start: one line for each folder,
with each source and config file and the names that the file defines, such as its functions, classes and exported
components. The agent then knows where things are and what it can reuse before its first command, so it does not
list the whole repo to find them. DensePack packs the map into one image, which costs about half the tokens of the
same text, so the map can hold names and still cost less than a list of files as text. Folders of tools, builds,
dependencies and migrations are skipped. Never raises: any error gives an empty map."""
import os
import re
import subprocess

BUDGET = 6000
SKIP = {"node_modules", ".git", "dist", "build", "out", "vendor", "venv", ".venv", "__pycache__", "coverage", ".next",
        "target", ".claude", ".github", ".vscode", ".idea", "versions", "migrations"}
CODE = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt", ".php", ".swift",
        ".cs", ".vue", ".svelte", ".sh", ".ps1"}
CONFIG = {"package.json", "pyproject.toml", "tsconfig.json", "components.json", "Cargo.toml", "go.mod", "Gemfile",
          "pom.xml", "build.gradle", "Makefile", "Dockerfile", "requirements.txt", "setup.py"}
# One pattern for each family of languages: a declaration at the start of a line, at the top level of the file.
DECLARATION = {
    "py": re.compile(r"^(?:async\s+def|def|class)\s+([A-Za-z]\w*)", re.M),
    "js": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|interface|type|enum)\s*\*?\s*"
                     r"([A-Za-z$][\w$]*)|^(?:function|class)\s+([A-Z][\w$]*)", re.M),
    "go": re.compile(r"^(?:func(?:\s*\([^)]*\))?|type)\s+([A-Z]\w*)", re.M),
    "rs": re.compile(r"^pub\s+(?:fn|struct|enum|trait)\s+(\w+)", re.M),
}
FAMILY = {".py": "py", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
          ".vue": "js", ".svelte": "js", ".go": "go", ".rs": "rs"}
EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}", re.M)
# Tests and generated files keep their file names but not the names inside: the agent reuses code, not tests.
NO_NAMES = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.\w+$|\.(test|spec|gen|d)\.\w+$")


def tracked_files(root):
    """The project's files as forward-slash paths: git's list, or a walk of the folder outside a repo."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=3,
                             encoding="utf-8", errors="replace").stdout
        files = [f for f in out.splitlines() if f]
        if files:
            return files
    except (OSError, subprocess.SubprocessError):
        pass
    files = []
    for top, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        rel = os.path.relpath(top, root).replace("\\", "/")
        files += [n if rel == "." else rel + "/" + n for n in names]
        if len(files) > 20000:
            break
    return files


def defined_names(path, limit=6):
    """The first names that a source file defines, in file order, or [] for a file of another kind."""
    family = FAMILY.get(os.path.splitext(path)[1])
    if not family:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(65536)
    except OSError:
        return []
    names = []
    for m in DECLARATION[family].finditer(text):
        names.append(next(g for g in m.groups() if g))
    if family == "js":
        for m in EXPORT_LIST.finditer(text):
            names += [p.split(" as ")[-1].strip() for p in m.group(1).split(",") if p.strip()]
    names = [n for n in dict.fromkeys(names) if not n.startswith("_")]
    return names[:limit] + (["..."] if len(names) > limit else [])


def build(root, budget=BUDGET):
    """The map as text, or "" when the project has no source or config files."""
    try:
        folders = {}
        for f in tracked_files(root):
            parts = f.split("/")
            name = parts[-1]
            if any(p in SKIP for p in parts[:-1]) or name == "__init__.py":
                continue
            if name in CONFIG or os.path.splitext(name)[1] in CODE:
                folders.setdefault("/".join(parts[:-1]) or ".", []).append(name)
        order = sorted(folders, key=lambda d: (d.count("/"), d))
        full, short = {}, {}
        for d in order:
            entries = []
            for name in sorted(folders[d]):
                path = name if d == "." else d + "/" + name
                names = [] if NO_NAMES.search(path) else defined_names(os.path.join(root, path))
                entries.append("%s (%s)" % (name, ", ".join(names)) if names else name)
            full[d] = "%s/: %s" % (d, "; ".join(entries))
            short[d] = "%s/: %s" % (d, ", ".join(sorted(folders[d])))
        # Every folder gets a line. Over the budget, test folders lose their file names first, then the deepest
        # folders lose their names, then their files.
        lines = dict(full)
        for d in sorted(order, key=lambda d: (not NO_NAMES.search(d + "/"), -d.count("/"))):
            if sum(len(l) + 1 for l in lines.values()) <= budget:
                break
            lines[d] = short[d] if len(short[d]) < 200 else "%s/: %d files" % (d, len(folders[d]))
        if not lines:
            return ""
        return ("Project map: each folder, its source and config files, and the names each file defines. "
                "List or read a folder from here directly.\n" + "\n".join(lines[d] for d in order))
    except Exception:  # noqa: BLE001 - a map must never break the start note
        return ""


if __name__ == "__main__":
    import sys
    print(build(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
