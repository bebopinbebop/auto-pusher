from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import defaultdict
from pathlib import Path, PurePosixPath

from git_progressor.analyzer.models import (
    AnalysisStatistics,
    AnalyzerLimits,
    Dependency,
    Evidence,
    FileClassification,
    ModuleComponent,
    ProjectAnalysis,
    TestInventory,
)
from git_progressor.exceptions import AnalysisError
from git_progressor.intake.manifest import file_sha256
from git_progressor.models import ManifestFile, ProjectManifest
from git_progressor.security import CredentialScanner

LANGUAGES = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".json": "JSON",
    ".jsx": "JavaScript",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".rs": "Rust",
    ".sh": "Shell",
    ".sql": "SQL",
    ".tf": "HCL / Terraform",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".yaml": "YAML",
    ".yml": "YAML",
}

FRAMEWORK_DEPENDENCIES = {
    "@aws-cdk/core": "AWS CDK",
    "@nestjs/core": "NestJS",
    "django": "Django",
    "express": "Express",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "jest": "Jest",
    "next": "Next.js",
    "pytest": "pytest",
    "react": "React",
    "react-native": "React Native",
    "spring-boot": "Spring Boot",
}

CONFIG_NAMES = {
    ".editorconfig",
    ".pre-commit-config.yaml",
    "Cargo.toml",
    "CMakeLists.txt",
    "go.mod",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tsconfig.json",
}


class MetadataReader:
    def __init__(
        self, root: Path, limits: AnalyzerLimits, scanner: CredentialScanner
    ) -> None:
        self.root = root
        self.limits = limits
        self.scanner = scanner
        self.bytes_read = 0
        self.warnings: set[str] = set()

    def text(self, relative: str) -> str | None:
        path = self.root / Path(relative)
        size = path.stat().st_size
        if size > self.limits.max_metadata_file_size:
            self.warnings.add(f"metadata file exceeds per-file limit: {relative}")
            return None
        if self.bytes_read + size > self.limits.max_analysis_bytes:
            self.warnings.add("metadata analysis byte limit reached")
            return None
        findings = self.scanner.scan_file(self.root, path)
        if findings:
            rules = ",".join(sorted({finding.rule for finding in findings}))
            self.warnings.add(f"suspicious metadata skipped: {relative} ({rules})")
            return None
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeError:
            self.warnings.add(f"non-UTF-8 metadata skipped: {relative}")
            return None
        self.bytes_read += size
        return value


class ProjectAnalyzer:
    def __init__(
        self, limits: AnalyzerLimits, scanner: CredentialScanner | None = None
    ) -> None:
        self.limits = limits
        self.scanner = scanner or CredentialScanner()

    def analyze(self, source: Path, manifest: ProjectManifest) -> ProjectAnalysis:
        source = source.resolve()
        if not source.is_dir() or source.is_symlink():
            raise AnalysisError(f"source revision is not a safe directory: {source}")
        ordered = tuple(sorted(manifest.files, key=lambda item: item.path))
        self._verify_manifest_files(source, ordered)
        selected = ordered[: self.limits.max_files]
        warnings: set[str] = set()
        if len(selected) < len(ordered):
            warnings.add(
                f"file analysis limit reached: analyzed {len(selected)} of {len(ordered)}"
            )
        reader = MetadataReader(source, self.limits, self.scanner)

        language_paths: dict[str, list[str]] = defaultdict(list)
        configuration: list[FileClassification] = []
        infrastructure: list[FileClassification] = []
        documentation: list[FileClassification] = []
        entrypoints: dict[str, list[str]] = defaultdict(list)
        test_paths: list[str] = []
        unit_files = 0
        integration_files = 0

        for item in selected:
            path = PurePosixPath(item.path)
            if (
                path.name.casefold() in self.scanner.BLOCKED_NAMES
                or path.suffix.casefold() in self.scanner.BLOCKED_SUFFIXES
            ):
                warnings.add(f"credential-shaped file excluded from analysis: {item.path}")
                continue
            suffix = path.suffix.lower()
            if suffix in LANGUAGES:
                language_paths[LANGUAGES[suffix]].append(item.path)
            if path.name in CONFIG_NAMES or path.name.startswith(".") and "config" in path.name:
                configuration.append(classification(item, "configuration"))
            infrastructure_kind = self._infrastructure_kind(item.path, reader)
            if infrastructure_kind:
                infrastructure.append(classification(item, infrastructure_kind))
            if self._is_documentation(path):
                documentation.append(classification(item, self._documentation_kind(path)))
            entrypoint = self._entrypoint_kind(path)
            if entrypoint:
                entrypoints[entrypoint].append(item.path)
            if self._is_test_file(path):
                test_paths.append(item.path)
                lowered = item.path.casefold()
                unit_files += int("unit" in path.parts or "/unit/" in lowered)
                integration_files += int(
                    "integration" in path.parts or "/integration/" in lowered
                )

        dependencies, metadata_entrypoints = self._dependencies(selected, reader)
        for name, paths in metadata_entrypoints.items():
            entrypoints[name].extend(paths)
        tools = self._tools(selected, dependencies, infrastructure, test_paths)
        test_frameworks = tuple(
            sorted(
                name
                for name in ("pytest", "Jest")
                if name in tools
            )
        )
        test_directories = tuple(
            sorted(
                {
                    self._test_directory(PurePosixPath(path))
                    for path in test_paths
                }
            )
        )
        modules = self._modules(selected)
        important = self._important_files(
            selected, configuration, infrastructure, documentation, entrypoints, test_paths
        )
        if len(important) == self.limits.max_important_files and len(selected) > len(important):
            warnings.add("important file selection limit reached")
        warnings.update(reader.warnings)

        payload = {
            "schema_version": 1,
            "analyzer_version": 1,
            "project_id": manifest.project_id,
            "source_revision": manifest.source_hash,
            "analysis_hash": "0" * 64,
            "limits": self.limits,
            "languages": tuple(
                Evidence(name=name, paths=tuple(paths))
                for name, paths in sorted(language_paths.items())
            ),
            "frameworks_and_tools": tuple(
                Evidence(name=name, paths=tuple(sorted(paths)))
                for name, paths in sorted(tools.items())
            ),
            "dependencies": dependencies,
            "tests": TestInventory(
                present=bool(test_paths),
                file_count=len(test_paths),
                frameworks=test_frameworks,
                directories=test_directories,
                unit_files=unit_files,
                integration_files=integration_files,
            ),
            "configuration": tuple(sorted(configuration, key=lambda item: item.path)),
            "infrastructure": tuple(sorted(infrastructure, key=lambda item: item.path)),
            "documentation": tuple(sorted(documentation, key=lambda item: item.path)),
            "entrypoints": tuple(
                Evidence(name=name, paths=tuple(sorted(set(paths))))
                for name, paths in sorted(entrypoints.items())
            ),
            "modules": modules,
            "important_files": important,
            "statistics": AnalysisStatistics(
                total_files=len(ordered),
                analyzed_files=len(selected),
                skipped_files=len(ordered) - len(selected),
                total_source_bytes=sum(item.size for item in ordered),
                metadata_bytes_read=reader.bytes_read,
                important_files_selected=len(important),
            ),
            "warnings": tuple(sorted(warnings)),
        }
        provisional = ProjectAnalysis.model_validate(payload)
        digest = analysis_sha256(provisional)
        return provisional.model_copy(update={"analysis_hash": digest})

    @staticmethod
    def _verify_manifest_files(source: Path, files: tuple[ManifestFile, ...]) -> None:
        for item in files:
            path = source / Path(item.path)
            if not path.is_file() or path.is_symlink():
                raise AnalysisError(f"manifest file is unavailable or unsafe: {item.path}")
            if path.stat().st_size != item.size or file_sha256(path) != item.sha256:
                raise AnalysisError(f"source revision does not match manifest: {item.path}")

    def _dependencies(
        self, files: tuple[ManifestFile, ...], reader: MetadataReader
    ) -> tuple[tuple[Dependency, ...], dict[str, list[str]]]:
        paths = {item.path for item in files}
        dependencies: set[tuple[str, str, str, str]] = set()
        entrypoints: dict[str, list[str]] = defaultdict(list)
        metadata_paths = {
            "Cargo.toml",
            "go.mod",
            "package.json",
            "pyproject.toml",
            "requirements.txt",
        }
        for path in sorted(paths & metadata_paths):
            text = reader.text(path)
            if text is None:
                continue
            try:
                if path == "pyproject.toml":
                    data = tomllib.loads(text)
                    for value in data.get("project", {}).get("dependencies", []):
                        name, specification = split_requirement(str(value))
                        dependencies.add(("python", name, specification, path))
                    for name in data.get("project", {}).get("scripts", {}):
                        entrypoints[f"console script:{name}"].append(path)
                elif path == "requirements.txt":
                    for line in text.splitlines():
                        value = line.strip()
                        if value and not value.startswith(("#", "-")):
                            name, specification = split_requirement(value)
                            dependencies.add(("python", name, specification, path))
                elif path == "package.json":
                    data = json.loads(text)
                    dependency_groups = (
                        "dependencies",
                        "devDependencies",
                        "peerDependencies",
                        "optionalDependencies",
                    )
                    for group in dependency_groups:
                        for name, specification in data.get(group, {}).items():
                            dependencies.add(("npm", name, str(specification), path))
                    for name in data.get("scripts", {}):
                        entrypoints[f"npm script:{name}"].append(path)
                elif path == "Cargo.toml":
                    data = tomllib.loads(text)
                    for name, specification in data.get("dependencies", {}).items():
                        dependencies.add(("cargo", name, str(specification), path))
                elif path == "go.mod":
                    for name, specification in parse_go_requirements(text):
                        dependencies.add(("go", name, specification, path))
            except (ValueError, TypeError, AttributeError) as exc:
                reader.warnings.add(f"metadata parse failed: {path} ({type(exc).__name__})")
        return (
            tuple(
                Dependency(ecosystem=e, name=n, specification=s, source_path=p)
                for e, n, s, p in sorted(dependencies)
            ),
            entrypoints,
        )

    @staticmethod
    def _tools(
        files: tuple[ManifestFile, ...],
        dependencies: tuple[Dependency, ...],
        infrastructure: list[FileClassification],
        test_paths: list[str],
    ) -> dict[str, list[str]]:
        tools: dict[str, list[str]] = defaultdict(list)
        for dependency in dependencies:
            lowered = dependency.name.casefold()
            for token, tool in FRAMEWORK_DEPENDENCIES.items():
                if lowered == token or token in lowered:
                    tools[tool].append(dependency.source_path)
        names = {PurePosixPath(item.path).name for item in files}
        file_tools = {
            "package.json": "Node.js",
            "pom.xml": "Maven",
            "build.gradle": "Gradle",
            "build.gradle.kts": "Gradle",
            "CMakeLists.txt": "CMake",
        }
        for marker, tool in file_tools.items():
            if marker in names:
                tools[tool].append(marker)
        for item in infrastructure:
            if item.kind == "terraform":
                tools["Terraform"].append(item.path)
            elif item.kind == "docker":
                tools["Docker"].append(item.path)
            elif item.kind == "kubernetes":
                tools["Kubernetes"].append(item.path)
            elif item.kind in {"aws-sam", "cloudformation"}:
                tools["AWS"].append(item.path)
        if any(PurePosixPath(path).name.startswith("test_") for path in test_paths):
            tools["pytest"].extend(test_paths)
        return tools

    @staticmethod
    def _infrastructure_kind(path: str, reader: MetadataReader) -> str | None:
        value = path.casefold()
        name = PurePosixPath(path).name.casefold()
        if path.endswith(".tf"):
            return "terraform"
        if name == "dockerfile" or name.startswith("docker-compose"):
            return "docker"
        if value.startswith(".github/workflows/"):
            return "github-actions"
        if name.endswith((".service", ".timer")):
            return "systemd"
        if "helm/" in value or name == "chart.yaml":
            return "helm"
        if path.endswith((".yaml", ".yml")):
            text = reader.text(path)
            if text and re.search(r"(?m)^kind:\s*(Deployment|Service|StatefulSet|DaemonSet)", text):
                return "kubernetes"
            if text and "Transform: AWS::Serverless" in text:
                return "aws-sam"
            if text and "AWSTemplateFormatVersion" in text:
                return "cloudformation"
        return None

    @staticmethod
    def _is_documentation(path: PurePosixPath) -> bool:
        value = path.as_posix().casefold()
        return (
            path.name.casefold().startswith(("readme", "contributing"))
            or value.startswith("docs/")
            or "/docs/" in value
            or "architecture" in path.name.casefold()
            or "adr" in path.name.casefold()
        )

    @staticmethod
    def _documentation_kind(path: PurePosixPath) -> str:
        name = path.name.casefold()
        if name.startswith("readme"):
            return "readme"
        if name.startswith("contributing"):
            return "contributing"
        if "adr" in name:
            return "adr"
        return "documentation"

    @staticmethod
    def _entrypoint_kind(path: PurePosixPath) -> str | None:
        name = path.name.casefold()
        conventional = {
            "app.py",
            "index.js",
            "index.ts",
            "main.py",
            "main.ts",
            "server.js",
            "server.py",
        }
        if name in conventional:
            return "conventional entrypoint"
        if name == "dockerfile":
            return "container entrypoint definition"
        if name in {"main.go", "main.rs"} or name.startswith("program."):
            return "language entrypoint"
        return None

    @staticmethod
    def _is_test_file(path: PurePosixPath) -> bool:
        value = path.as_posix().casefold()
        name = path.name.casefold()
        return (
            any(part.casefold() in {"test", "tests", "__tests__"} for part in path.parts)
            or name.startswith("test_")
            or ".test." in name
            or ".spec." in name
            or value.endswith("tests.cs")
        )

    @staticmethod
    def _test_directory(path: PurePosixPath) -> str:
        for index, part in enumerate(path.parts[:-1]):
            if part.casefold() in {"test", "tests", "__tests__"}:
                return PurePosixPath(*path.parts[: index + 1]).as_posix()
        return path.parent.as_posix()

    @staticmethod
    def _modules(files: tuple[ManifestFile, ...]) -> tuple[ModuleComponent, ...]:
        components: set[tuple[str, str]] = set()
        for item in files:
            path = PurePosixPath(item.path)
            source_roots = {"app", "apps", "lib", "packages", "services", "src"}
            if len(path.parts) > 1 and path.parts[0] in source_roots:
                depth = 2 if len(path.parts) > 2 else 1
                components.add((PurePosixPath(*path.parts[:depth]).as_posix(), "source module"))
            if path.name == "__init__.py" and len(path.parts) > 1:
                components.add((path.parent.as_posix(), "python package"))
            if path.suffix == ".tf" and len(path.parts) > 1:
                components.add((path.parent.as_posix(), "terraform module"))
        return tuple(ModuleComponent(path=path, kind=kind) for path, kind in sorted(components))

    def _important_files(
        self,
        files: tuple[ManifestFile, ...],
        configuration: list[FileClassification],
        infrastructure: list[FileClassification],
        documentation: list[FileClassification],
        entrypoints: dict[str, list[str]],
        tests: list[str],
    ) -> tuple[str, ...]:
        priority: dict[str, int] = {}
        for item in configuration:
            priority[item.path] = min(priority.get(item.path, 99), 0)
        for paths in entrypoints.values():
            for path in paths:
                priority[path] = min(priority.get(path, 99), 1)
        for item in infrastructure:
            priority[item.path] = min(priority.get(item.path, 99), 2)
        for item in documentation:
            priority[item.path] = min(priority.get(item.path, 99), 3)
        for path in tests:
            priority[path] = min(priority.get(path, 99), 4)
        for item in files:
            if PurePosixPath(item.path).suffix.lower() in LANGUAGES:
                priority[item.path] = min(priority.get(item.path, 99), 5)
        ranked = sorted(priority, key=lambda path: (priority[path], path))
        return tuple(ranked[: self.limits.max_important_files])


def classification(item: ManifestFile, kind: str) -> FileClassification:
    return FileClassification(path=item.path, kind=kind, size=item.size)


def split_requirement(value: str) -> tuple[str, str]:
    match = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", value.strip())
    return (match.group(1), match.group(2).strip()) if match else (value.strip(), "")


def parse_go_requirements(value: str) -> tuple[tuple[str, str], ...]:
    dependencies: list[tuple[str, str]] = []
    in_block = False
    for line in value.splitlines():
        stripped = line.strip()
        if stripped == "require (":
            in_block = True
        elif stripped == ")":
            in_block = False
        elif stripped.startswith("require ") or in_block:
            fields = stripped.removeprefix("require ").split()
            if len(fields) >= 2:
                dependencies.append((fields[0], fields[1]))
    return tuple(dependencies)


def analysis_sha256(analysis: ProjectAnalysis) -> str:
    payload = analysis.model_dump(mode="json", exclude={"analysis_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
