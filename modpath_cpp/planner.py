from __future__ import annotations

import json
import os
import re
import shlex
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INCLUDE_RE = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)[">]')
DEFINE_RE = re.compile(r'^\s*#\s*define\b')

HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".inc", ".ipp"}


@dataclass
class Candidate:
    header: str
    include_frequency: int
    macro_defines: int
    in_cycle: bool
    risk_score: int
    risk_level: str
    recommendation: str
    rationale: list[str]
    suggested_module: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "include_frequency": self.include_frequency,
            "macro_defines": self.macro_defines,
            "in_cycle": self.in_cycle,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "suggested_module": self.suggested_module,
        }


@dataclass
class PlannerReport:
    input_file: str
    project_root: str
    translation_units: int
    scanned_headers: int
    cycle_header_count: int
    candidates: list[Candidate]
    phases: dict[str, Any]
    readiness_checks: list[dict[str, str]]
    unresolved_includes: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_file": self.input_file,
            "project_root": self.project_root,
            "summary": {
                "translation_units": self.translation_units,
                "scanned_headers": self.scanned_headers,
                "cycle_header_count": self.cycle_header_count,
                "unresolved_include_count": len(self.unresolved_includes),
            },
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "phases": self.phases,
            "readiness_checks": self.readiness_checks,
            "unresolved_includes": self.unresolved_includes,
        }


@dataclass
class TranslationUnit:
    path: Path
    include_dirs: list[Path]
    std_flag: str


def analyze_compile_commands(compile_commands_path: str | Path, top: int = 10) -> PlannerReport:
    compile_commands = Path(compile_commands_path).expanduser().resolve()
    entries = _load_compile_commands(compile_commands)

    tus = _collect_translation_units(entries, compile_commands)
    if not tus:
        raise ValueError("No translation units found in compile_commands.json")

    all_include_dirs = _unique_paths(
        [include_dir for tu in tus for include_dir in tu.include_dirs]
    )
    project_root = _infer_project_root(
        [tu.path for tu in tus] + all_include_dirs,
        compile_commands.parent,
    )

    include_tokens = Counter()
    include_frequency: Counter[Path] = Counter()
    unresolved_includes: list[dict[str, str]] = []
    header_graph: dict[Path, set[Path]] = defaultdict(set)
    macro_counts: dict[Path, int] = {}

    header_queue: deque[Path] = deque()

    for tu in tus:
        includes = _parse_includes(tu.path)
        for kind, include_name in includes:
            include_tokens[_token(kind, include_name)] += 1
            resolved = _resolve_include(
                include_name,
                kind,
                tu.path,
                tu.include_dirs,
            )
            if not resolved:
                if kind == '"':
                    unresolved_includes.append(
                        {
                            "from": _relative_display(tu.path, project_root),
                            "include": _token(kind, include_name),
                        }
                    )
                continue

            if _is_header(resolved):
                include_frequency[resolved] += 1
                if _is_project_path(resolved, project_root):
                    header_queue.append(resolved)

    scanned_headers: set[Path] = set()

    while header_queue:
        header = header_queue.popleft()
        if header in scanned_headers or not header.exists():
            continue

        scanned_headers.add(header)
        header_graph.setdefault(header, set())
        macro_counts[header] = _count_defines(header)

        for kind, include_name in _parse_includes(header):
            include_tokens[_token(kind, include_name)] += 1
            resolved = _resolve_include(
                include_name,
                kind,
                header,
                all_include_dirs,
            )
            if not resolved:
                if kind == '"':
                    unresolved_includes.append(
                        {
                            "from": _relative_display(header, project_root),
                            "include": _token(kind, include_name),
                        }
                    )
                continue

            if not _is_header(resolved):
                continue

            include_frequency[resolved] += 1
            if _is_project_path(resolved, project_root):
                header_graph[header].add(resolved)
                header_queue.append(resolved)

    cycle_nodes = _detect_cycle_nodes(header_graph)

    all_project_headers = {
        path
        for path in set(include_frequency.keys()) | set(header_graph.keys())
        if _is_project_path(path, project_root) and _is_header(path)
    }

    candidates: list[Candidate] = []
    for header in sorted(all_project_headers):
        include_count = include_frequency.get(header, 0)
        macro_count = macro_counts.get(header, _count_defines(header))
        in_cycle = header in cycle_nodes

        risk_score, rationale = _risk_score(
            header=header,
            include_frequency=include_count,
            macro_count=macro_count,
            in_cycle=in_cycle,
        )

        risk_level = _risk_level(risk_score)
        recommendation = _recommendation(risk_score, in_cycle)
        suggested_module = _suggest_module_name(header, project_root)

        candidates.append(
            Candidate(
                header=_relative_display(header, project_root),
                include_frequency=include_count,
                macro_defines=macro_count,
                in_cycle=in_cycle,
                risk_score=risk_score,
                risk_level=risk_level,
                recommendation=recommendation,
                rationale=rationale,
                suggested_module=suggested_module,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.include_frequency * 12 - candidate.risk_score,
            candidate.include_frequency,
            -candidate.risk_score,
            candidate.header,
        ),
        reverse=True,
    )
    candidates = candidates[:top]

    readiness_checks = _build_readiness_checks(
        tus=tus,
        macro_counts=macro_counts,
        cycle_nodes=cycle_nodes,
        unresolved_count=len(unresolved_includes),
    )

    phases = _build_phases(
        candidates=candidates,
        include_tokens=include_tokens,
        readiness_checks=readiness_checks,
    )

    return PlannerReport(
        input_file=str(compile_commands),
        project_root=str(project_root),
        translation_units=len(tus),
        scanned_headers=len(scanned_headers),
        cycle_header_count=len(cycle_nodes),
        candidates=candidates,
        phases=phases,
        readiness_checks=readiness_checks,
        unresolved_includes=unresolved_includes[:50],
    )


def format_report(report: PlannerReport) -> str:
    lines: list[str] = []
    lines.append("modpath-cpp migration plan")
    lines.append(f"Input: {report.input_file}")
    lines.append(f"Project root: {report.project_root}")
    lines.append(
        "Scanned: "
        f"{report.translation_units} translation units, "
        f"{report.scanned_headers} headers, "
        f"{report.cycle_header_count} cycle-involved headers"
    )
    lines.append("")

    lines.append("Top migration candidates")
    if not report.candidates:
        lines.append("- No project headers were discovered from the input metadata.")
    else:
        for idx, candidate in enumerate(report.candidates, start=1):
            lines.append(
                f"{idx}. {candidate.header} "
                f"(includes={candidate.include_frequency}, risk={candidate.risk_score}/100 {candidate.risk_level})"
            )
            lines.append(f"   recommendation: {candidate.recommendation}")
            lines.append(f"   module hint: {candidate.suggested_module}")
            for reason in candidate.rationale[:3]:
                lines.append(f"   - {reason}")

    lines.append("")
    lines.append("Phased plan")

    p1 = report.phases["p1_header_units"]
    lines.append("P1) Header units")
    for item in p1["actions"]:
        lines.append(f"- {item}")

    p2 = report.phases["p2_named_modules"]
    lines.append("P2) Named modules")
    for item in p2["actions"]:
        lines.append(f"- {item}")

    p3 = report.phases["p3_import_std_readiness"]
    lines.append("P3) import std readiness")
    for check in p3["checks"]:
        lines.append(f"- [{check['status']}] {check['title']}: {check['details']}")

    if report.unresolved_includes:
        lines.append("")
        lines.append(
            f"Unresolved includes (showing first {len(report.unresolved_includes)}):"
        )
        for unresolved in report.unresolved_includes[:10]:
            lines.append(f"- {unresolved['from']}: {unresolved['include']}")

    return "\n".join(lines)


def _load_compile_commands(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"compile_commands file not found: {path}")

    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    if not isinstance(payload, list):
        raise ValueError("compile_commands.json must be a JSON array")

    return [entry for entry in payload if isinstance(entry, dict)]


def _collect_translation_units(
    entries: list[dict[str, Any]], compile_commands_path: Path
) -> list[TranslationUnit]:
    tus: list[TranslationUnit] = []

    for entry in entries:
        file_value = entry.get("file")
        if not file_value:
            continue

        directory_raw = entry.get("directory")
        if directory_raw:
            directory = Path(directory_raw)
            if not directory.is_absolute():
                directory = (compile_commands_path.parent / directory).resolve()
            else:
                directory = directory.resolve()
        else:
            directory = compile_commands_path.parent.resolve()

        file_path = Path(file_value)
        if not file_path.is_absolute():
            file_path = (directory / file_path).resolve()
        else:
            file_path = file_path.resolve()

        args = _extract_args(entry)
        include_dirs = _extract_include_dirs(args, directory)
        std_flag = _extract_std_flag(args)

        tus.append(
            TranslationUnit(
                path=file_path,
                include_dirs=include_dirs,
                std_flag=std_flag,
            )
        )

    return tus


def _extract_args(entry: dict[str, Any]) -> list[str]:
    if isinstance(entry.get("arguments"), list):
        return [str(arg) for arg in entry["arguments"]]

    command = entry.get("command")
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()

    return []


def _extract_include_dirs(args: list[str], directory: Path) -> list[Path]:
    include_dirs: list[Path] = []
    idx = 0

    while idx < len(args):
        token = args[idx]

        value: str | None = None
        if token in {"-I", "/I", "-isystem"} and idx + 1 < len(args):
            value = args[idx + 1]
            idx += 1
        elif token.startswith("-I") and len(token) > 2:
            value = token[2:]
        elif token.startswith("/I") and len(token) > 2:
            value = token[2:]
        elif token.startswith("-isystem") and len(token) > len("-isystem"):
            value = token[len("-isystem") :]

        if value:
            path = Path(value)
            if not path.is_absolute():
                path = (directory / path).resolve()
            else:
                path = path.resolve()
            include_dirs.append(path)

        idx += 1

    return _unique_paths(include_dirs)


def _extract_std_flag(args: list[str]) -> str:
    for token in args:
        if token.startswith("-std="):
            return token[len("-std=") :].lower()
        if token.startswith("/std:"):
            return token[len("/std:") :].lower()
    return "unknown"


def _is_cxx20_or_newer(std_flag: str) -> bool:
    value = std_flag.lower()
    if value == "unknown":
        return False

    if "c++2a" in value or "c++2b" in value:
        return True

    match = re.search(r"\+\+(\d+)", value)
    if not match:
        return False

    try:
        return int(match.group(1)) >= 20
    except ValueError:
        return False


def _infer_project_root(paths: list[Path], fallback: Path) -> Path:
    existing = [str(path) for path in paths if path.exists()]
    if not existing:
        return fallback.resolve()

    common = Path(os.path.commonpath(existing))
    if common.is_file():
        return common.parent.resolve()
    return common.resolve()


def _parse_includes(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []

    includes: list[tuple[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                match = INCLUDE_RE.match(line)
                if match:
                    includes.append((match.group(1), match.group(2).strip()))
    except OSError:
        return []

    return includes


def _resolve_include(
    include_name: str,
    include_kind: str,
    including_file: Path,
    include_dirs: list[Path],
) -> Path | None:
    include_path = Path(include_name)
    if include_path.is_absolute() and include_path.exists():
        return include_path.resolve()

    candidates: list[Path] = []

    if include_kind == '"':
        candidates.append((including_file.parent / include_path).resolve())

    for include_dir in include_dirs:
        candidates.append((include_dir / include_path).resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _is_header(path: Path) -> bool:
    return path.suffix.lower() in HEADER_SUFFIXES


def _is_project_path(path: Path, project_root: Path) -> bool:
    try:
        path.resolve().relative_to(project_root.resolve())
        return True
    except ValueError:
        return False


def _count_defines(path: Path) -> int:
    if not path.exists() or not _is_header(path):
        return 0

    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                if DEFINE_RE.match(line):
                    count += 1
    except OSError:
        return 0

    return count


def _detect_cycle_nodes(graph: dict[Path, set[Path]]) -> set[Path]:
    cycle_nodes: set[Path] = set()
    visited: set[Path] = set()
    on_stack: set[Path] = set()
    stack: list[Path] = []
    position: dict[Path, int] = {}

    def dfs(node: Path) -> None:
        visited.add(node)
        on_stack.add(node)
        position[node] = len(stack)
        stack.append(node)

        for child in graph.get(node, set()):
            if child not in graph:
                continue

            if child not in visited:
                dfs(child)
            elif child in on_stack:
                start = position.get(child, 0)
                cycle_nodes.update(stack[start:])

        stack.pop()
        on_stack.remove(node)
        position.pop(node, None)

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycle_nodes


def _risk_score(
    *,
    header: Path,
    include_frequency: int,
    macro_count: int,
    in_cycle: bool,
) -> tuple[int, list[str]]:
    risk = 10
    rationale: list[str] = [f"included {include_frequency} time(s) across scanned files"]

    if macro_count:
        macro_penalty = min(55, macro_count * 5)
        risk += macro_penalty
        if macro_count >= 8:
            rationale.append(f"macro-heavy: {macro_count} #define directives")
        else:
            rationale.append(f"contains {macro_count} #define directives")
    else:
        rationale.append("no #define directives found")

    if in_cycle:
        risk += 30
        rationale.append("participates in an include cycle")

    if header.suffix.lower() == ".h":
        risk += 10
        rationale.append(".h extension may indicate C/C++ mixed usage")

    if include_frequency <= 1:
        risk += 8
        rationale.append("low reuse means lower migration payoff")
    elif include_frequency >= 4:
        risk = max(0, risk - 6)
        rationale.append("high reuse improves migration payoff")

    risk = max(0, min(100, risk))
    return risk, rationale


def _risk_level(score: int) -> str:
    if score <= 30:
        return "low"
    if score <= 65:
        return "medium"
    return "high"


def _recommendation(risk_score: int, in_cycle: bool) -> str:
    if in_cycle:
        return "refactor include cycle before module migration"
    if risk_score <= 30:
        return "P1 header unit candidate"
    if risk_score <= 65:
        return "P2 named module pilot"
    return "defer until macro usage is reduced"


def _suggest_module_name(path: Path, project_root: Path) -> str:
    rel = _relative_display(path, project_root)
    if rel.startswith("include/"):
        rel = rel[len("include/") :]

    stem = str(Path(rel).with_suffix(""))
    stem = re.sub(r"[^a-zA-Z0-9/._-]", "", stem)
    stem = stem.replace("/", ".").replace("-", "_")
    stem = re.sub(r"\.{2,}", ".", stem).strip(".")
    return stem or "unnamed.module"


def _build_readiness_checks(
    *,
    tus: list[TranslationUnit],
    macro_counts: dict[Path, int],
    cycle_nodes: set[Path],
    unresolved_count: int,
) -> list[dict[str, str]]:
    non_cxx20 = [tu for tu in tus if not _is_cxx20_or_newer(tu.std_flag)]

    heavy_macro_headers = [
        header
        for header, macro_count in macro_counts.items()
        if macro_count >= 8
    ]

    checks: list[dict[str, str]] = []

    checks.append(
        {
            "title": "C++20 compiler mode coverage",
            "status": "pass" if not non_cxx20 else "warn",
            "details": (
                "All translation units appear to use C++20+ flags"
                if not non_cxx20
                else f"{len(non_cxx20)} TU(s) are below C++20 or missing -std flag"
            ),
        }
    )

    checks.append(
        {
            "title": "Include cycle cleanup",
            "status": "pass" if not cycle_nodes else "warn",
            "details": (
                "No include cycles detected"
                if not cycle_nodes
                else f"{len(cycle_nodes)} header(s) are part of cycle(s)"
            ),
        }
    )

    checks.append(
        {
            "title": "Macro-heavy header reduction",
            "status": "pass" if not heavy_macro_headers else "warn",
            "details": (
                "No macro-heavy headers detected"
                if not heavy_macro_headers
                else f"{len(heavy_macro_headers)} header(s) have >= 8 #define directives"
            ),
        }
    )

    checks.append(
        {
            "title": "Include resolution quality",
            "status": "pass" if unresolved_count == 0 else "warn",
            "details": (
                "All scanned includes resolved"
                if unresolved_count == 0
                else f"{unresolved_count} unresolved include(s); verify include paths"
            ),
        }
    )

    return checks


def _build_phases(
    *,
    candidates: list[Candidate],
    include_tokens: Counter,
    readiness_checks: list[dict[str, str]],
) -> dict[str, Any]:
    p1_project = [
        candidate
        for candidate in candidates
        if candidate.recommendation == "P1 header unit candidate"
        and candidate.include_frequency >= 2
    ][:5]

    p1_system = [
        (token, count)
        for token, count in include_tokens.most_common()
        if token.startswith("<") and count >= 2
    ][:5]

    p1_actions: list[str] = []
    if p1_project:
        for candidate in p1_project:
            p1_actions.append(
                f"Convert {candidate.header} to a header unit pilot (risk {candidate.risk_score})"
            )
    if p1_system:
        system_headers = ", ".join(
            f"{token} ({count}x)" for token, count in p1_system
        )
        p1_actions.append(
            f"Evaluate toolchain support for standard/third-party header units: {system_headers}"
        )
    if not p1_actions:
        p1_actions.append("Start with one low-risk, high-frequency project header as a pilot")

    p2_candidates = [
        candidate
        for candidate in candidates
        if candidate.risk_score <= 65
        and not candidate.in_cycle
        and candidate.include_frequency >= 2
    ][:5]

    p2_actions: list[str] = []
    if p2_candidates:
        for candidate in p2_candidates:
            p2_actions.append(
                f"Prototype named module '{candidate.suggested_module}' from {candidate.header}"
            )
    else:
        p2_actions.append(
            "No safe named-module candidates yet; reduce macro usage and break cycles first"
        )

    return {
        "p1_header_units": {
            "goal": "Reduce parse cost by importing stable headers as header units.",
            "actions": p1_actions,
        },
        "p2_named_modules": {
            "goal": "Promote stable components to named modules with explicit interfaces.",
            "actions": p2_actions,
        },
        "p3_import_std_readiness": {
            "goal": "Prepare for adopting import std where supported by toolchain.",
            "checks": readiness_checks,
            "actions": [
                "Ensure all TUs compile in C++20+ mode",
                "Eliminate include cycles and shrink macro-heavy public headers",
                "Validate compiler/libstdc++ or libc++ support for import std in CI",
            ],
        },
    }


def _relative_display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _token(kind: str, include_name: str) -> str:
    if kind == "<":
        return f"<{include_name}>"
    return f'"{include_name}"'
