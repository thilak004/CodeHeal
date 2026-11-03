"""Dependency analysis for detecting security issues and outdated packages."""
from __future__ import annotations

import re
from typing import Any


# Known vulnerable packages (simplified list - in production use CVE database)
KNOWN_VULNERABILITIES = {
    "django": {
        "2.2.0": ["SQL injection vulnerability"],
        "3.0.0": ["XSS vulnerability in admin"],
    },
    "requests": {
        "2.6.0": ["Vulnerability in certificate verification"],
        "2.5.0": ["Security issue with SSL"],
    },
    "flask": {
        "0.12.0": ["JSON encoding vulnerability"],
    },
    "numpy": {
        "1.16.0": ["Memory safety issue"],
    },
    "pillow": {
        "5.0.0": ["Buffer overflow vulnerability"],
    },
}

# Recommended minimum versions
RECOMMENDED_VERSIONS = {
    "django": "4.2",
    "requests": "2.31",
    "flask": "3.0",
    "numpy": "1.24",
    "pillow": "10.0",
    "pandas": "2.0",
    "scipy": "1.10",
    "tensorflow": "2.13",
    "pytorch": "2.0",
    "sqlalchemy": "2.0",
    "pytest": "7.4",
    "black": "23.9",
    "mypy": "1.5",
}


def _extract_python_dependencies(source: str) -> list[dict[str, Any]]:
    """Extract Python dependencies from source code (imports)."""
    dependencies = []

    # Standard library modules to skip
    stdlib = {
        "os", "sys", "json", "re", "time", "datetime", "math", "random",
        "collections", "itertools", "functools", "pathlib", "logging",
        "unittest", "typing", "io", "hashlib", "hmac", "base64",
        "urllib", "http", "socket", "ssl", "struct", "pickle",
        "csv", "sqlite3", "argparse", "configparser", "subprocess",
    }

    # Find all imports
    import_patterns = [
        r"^import\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
        r"^from\s+([a-zA-Z_][a-zA-Z0-9_\.]*)\s+import",
    ]

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        for pattern in import_patterns:
            match = re.search(pattern, stripped)
            if match:
                module = match.group(1).split(".")[0]
                if module not in stdlib and module not in [d["name"] for d in dependencies]:
                    dependencies.append({
                        "name": module,
                        "version": None,
                        "source": "detected_from_imports",
                    })

    return dependencies


def _extract_requirements_txt(content: str) -> list[dict[str, Any]]:
    """Extract dependencies from requirements.txt format."""
    dependencies = []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Parse package==version format
        match = re.match(r"([a-zA-Z0-9\-_]+)(==|>=|<=|>|<|~=)([0-9\.]+)", line)
        if match:
            name, operator, version = match.groups()
            dependencies.append({
                "name": name.lower(),
                "version": version,
                "operator": operator,
                "source": "requirements.txt",
            })
        else:
            # Just package name
            match = re.match(r"([a-zA-Z0-9\-_]+)", line)
            if match:
                dependencies.append({
                    "name": match.group(1).lower(),
                    "version": None,
                    "source": "requirements.txt",
                })

    return dependencies


def _extract_package_json(content: str) -> list[dict[str, Any]]:
    """Extract dependencies from package.json format."""
    dependencies = []

    # Simple regex parsing (in production, use proper JSON parsing)
    import re

    # Match "package": "version"
    pattern = r'"([a-zA-Z0-9\-_/@]+)"\s*:\s*"([^"]+)"'

    for match in re.finditer(pattern, content):
        name, version = match.groups()
        if name not in ["name", "version", "description", "main", "scripts"]:
            dependencies.append({
                "name": name,
                "version": version,
                "source": "package.json",
            })

    return dependencies


def _extract_pom_xml(content: str) -> list[dict[str, Any]]:
    """Extract dependencies from pom.xml (Java) format."""
    dependencies = []

    # Simple regex parsing for Maven
    pattern = r"<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>"

    for match in re.finditer(pattern, content):
        artifact_id, version = match.groups()
        dependencies.append({
            "name": artifact_id,
            "version": version,
            "source": "pom.xml",
        })

    return dependencies


def _extract_gemfile(content: str) -> list[dict[str, Any]]:
    """Extract dependencies from Gemfile (Ruby) format."""
    dependencies = []

    # Match gem 'name', '~> version' or gem 'name'
    pattern = r'gem\s+[\'"]([^\'"]+)[\'"](?:\s*,\s*[\'"]([^\'"]+)[\'"])?'

    for match in re.finditer(pattern, content):
        name, version = match.groups()
        dependencies.append({
            "name": name,
            "version": version,
            "source": "Gemfile",
        })

    return dependencies


def _check_vulnerability(package: str, version: str | None) -> list[str]:
    """Check if package/version has known vulnerabilities."""
    issues = []

    package_lower = package.lower()
    if package_lower in KNOWN_VULNERABILITIES and version:
        vuln_dict = KNOWN_VULNERABILITIES[package_lower]
        if version in vuln_dict:
            issues.extend(vuln_dict[version])

    return issues


def _check_outdated(package: str, version: str | None) -> tuple[bool, str | None]:
    """Check if package version is outdated."""
    if not version:
        return False, None

    package_lower = package.lower()
    if package_lower in RECOMMENDED_VERSIONS:
        recommended = RECOMMENDED_VERSIONS[package_lower]
        # Simple version comparison (naive approach)
        try:
            current_parts = [int(x) for x in version.split(".")[:2]]
            recommended_parts = [int(x) for x in recommended.split(".")[:2]]

            if current_parts < recommended_parts:
                return True, recommended
        except (ValueError, IndexError):
            pass

    return False, None


def _check_unused_imports(source: str, language: str) -> list[dict[str, Any]]:
    """Detect unused imports in source code."""
    issues = []

    if language != "python":
        return issues

    # Simple detection: find imports not used in the code
    import_matches = list(re.finditer(r"^(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", source, re.MULTILINE))

    unused = []
    for match in import_matches:
        module_name = match.group(1).split(".")[0]
        # Simple check: if module name not found after import statement
        rest_of_code = source[match.end():]

        if not re.search(rf"\b{re.escape(module_name)}\b", rest_of_code):
            unused.append({
                "module": module_name,
                "line": source[:match.start()].count("\n") + 1,
            })

    return unused


def analyze_dependencies(source: str, language: str = "python") -> dict[str, Any]:
    """Analyze external dependencies for security and version issues.

    Detects:
    - Known vulnerabilities
    - Outdated packages
    - Unused imports
    - Missing version pinning
    """

    dependencies = []
    source_format = None

    # Detect dependency format based on language/content
    if language == "python":
        if "import" in source or "from" in source:
            dependencies = _extract_python_dependencies(source)
            source_format = "python_imports"

        if "==" in source and ("\n" in source or len(source) > 100):
            req_deps = _extract_requirements_txt(source)
            if req_deps:
                dependencies.extend(req_deps)
                source_format = "requirements.txt"

    elif language == "javascript":
        pkg_deps = _extract_package_json(source)
        if pkg_deps:
            dependencies = pkg_deps
            source_format = "package.json"

    elif language == "java":
        pom_deps = _extract_pom_xml(source)
        if pom_deps:
            dependencies = pom_deps
            source_format = "pom.xml"

    elif language == "ruby":
        gemfile_deps = _extract_gemfile(source)
        if gemfile_deps:
            dependencies = gemfile_deps
            source_format = "Gemfile"

    # Analyze dependencies for issues
    issues = []
    security_issues = []
    outdated_packages = []

    for dep in dependencies:
        name = dep["name"]
        version = dep.get("version")

        # Check vulnerabilities
        vulns = _check_vulnerability(name, version)
        if vulns:
            for vuln in vulns:
                security_issues.append({
                    "type": "vulnerability",
                    "package": name,
                    "version": version,
                    "issue": vuln,
                    "severity": "high",
                })

        # Check if outdated
        is_outdated, recommended = _check_outdated(name, version)
        if is_outdated:
            outdated_packages.append({
                "package": name,
                "current_version": version,
                "recommended_version": recommended,
                "severity": "medium",
            })

        # Check if version is pinned
        if not version and name not in ["__all__", "ABC"]:
            issues.append({
                "type": "unpinned_version",
                "package": name,
                "message": f"Package '{name}' has no version specified",
                "severity": "low",
            })

    # Check for unused imports
    unused_imports = _check_unused_imports(source, language)

    # Build summary
    summary = {
        "total_dependencies": len(dependencies),
        "security_issues": len(security_issues),
        "outdated_packages": len(outdated_packages),
        "unused_imports": len(unused_imports),
        "critical_issues": len([i for i in security_issues if i.get("severity") == "high"]),
    }

    # Determine overall status
    if security_issues:
        status = "critical" if summary["critical_issues"] > 0 else "warning"
    elif outdated_packages:
        status = "warning"
    elif unused_imports or issues:
        status = "info"
    else:
        status = "clean"

    return {
        "status": status,
        "language": language,
        "source_format": source_format,
        "summary": summary,
        "dependencies": dependencies,
        "security_issues": security_issues,
        "outdated_packages": outdated_packages,
        "unused_imports": unused_imports,
        "other_issues": issues,
        "recommendations": _get_dependency_recommendations(
            summary, security_issues, outdated_packages, unused_imports
        ),
    }


def _get_dependency_recommendations(
    summary: dict[str, int],
    security_issues: list[dict[str, Any]],
    outdated_packages: list[dict[str, Any]],
    unused_imports: list[dict[str, Any]],
) -> list[str]:
    """Generate recommendations based on dependency analysis."""
    recommendations = []

    if security_issues:
        critical = len([i for i in security_issues if i.get("severity") == "high"])
        recommendations.append(f"⚠ {critical} critical security issues found. Update immediately.")

    if outdated_packages:
        recommendations.append(f"Update {len(outdated_packages)} outdated package(s) to get latest features and patches.")

    if unused_imports:
        recommendations.append(f"Remove {len(unused_imports)} unused import(s) to clean up code.")

    if summary.get("total_dependencies", 0) > 20:
        recommendations.append("Consider breaking project into smaller modules with fewer dependencies.")

    if not recommendations:
        recommendations.append("✓ Dependencies look good! Keep monitoring for updates.")

    return recommendations
