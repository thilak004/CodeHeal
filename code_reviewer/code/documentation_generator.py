"""Auto-generate documentation and docstrings for code."""
from __future__ import annotations

import ast
import re
from typing import Any


def _generate_python_docstring(func_node: ast.FunctionDef | ast.AsyncFunctionDef, style: str = "google") -> str:
    """Generate a docstring for a Python function."""
    func_name = func_node.name
    args = func_node.args

    # Extract argument names (excluding self)
    arg_names = [arg.arg for arg in args.args if arg.arg != "self"]

    # Extract type hints if available
    arg_types = {}
    for arg in args.args:
        if arg.annotation:
            try:
                arg_types[arg.arg] = ast.unparse(arg.annotation)
            except:
                arg_types[arg.arg] = "Any"

    # Get return type if available
    return_type = "Any"
    if func_node.returns:
        try:
            return_type = ast.unparse(func_node.returns)
        except:
            return_type = "Any"

    if style == "google":
        docstring = f'"""{func_name}.\n\n'

        if arg_names:
            docstring += "Args:\n"
            for arg in arg_names:
                arg_type = arg_types.get(arg, "Any")
                docstring += f"    {arg} ({arg_type}): Description of {arg}.\n"

        docstring += f"\nReturns:\n    {return_type}: Description of return value.\n"
        docstring += '"""'

    elif style == "numpy":
        docstring = f'"""{func_name}.\n\n'

        if arg_names:
            docstring += "Parameters\n----------\n"
            for arg in arg_names:
                arg_type = arg_types.get(arg, "Any")
                docstring += f"{arg} : {arg_type}\n    Description of {arg}.\n"

        docstring += f"\nReturns\n-------\n{return_type}\n    Description of return value.\n"
        docstring += '"""'

    else:  # default
        docstring = f'"""{func_name}.\n\n'
        docstring += f"Args: {', '.join(arg_names) if arg_names else 'None'}\n"
        docstring += f"Returns: {return_type}\n"
        docstring += '"""'

    return docstring


def _extract_function_purpose(source: str, func_name: str, line_num: int) -> str:
    """Try to infer function purpose from code and naming."""
    # Simple heuristics based on function name
    name_lower = func_name.lower()

    if any(word in name_lower for word in ["get", "fetch", "retrieve"]):
        return "Retrieve and return data."
    elif any(word in name_lower for word in ["set", "update", "modify", "change"]):
        return "Update or modify the given data."
    elif any(word in name_lower for word in ["calculate", "compute", "process"]):
        return "Calculate or process the input."
    elif any(word in name_lower for word in ["validate", "check", "verify"]):
        return "Validate or verify the input."
    elif any(word in name_lower for word in ["create", "make", "build", "generate"]):
        return "Create and return a new object."
    elif any(word in name_lower for word in ["delete", "remove", "clear"]):
        return "Delete or remove the specified item."
    else:
        return f"Perform operations related to {func_name}."


def _generate_jsdoc(func_node: dict[str, Any]) -> str:
    """Generate JSDoc documentation for JavaScript function."""
    func_name = func_node.get("name", "function")
    params = func_node.get("params", [])

    doc = f"/**\n * {_extract_function_purpose('', func_name, 0)}\n"

    for param in params:
        doc += f" * @param {{{param}}} {param} - Description of {param}.\n"

    doc += f" * @return {{*}} Description of return value.\n"
    doc += " */"

    return doc


def _generate_javadoc(class_name: str = "", method_name: str = "", params: list[str] = None) -> str:
    """Generate JavaDoc documentation for Java class/method."""
    if params is None:
        params = []

    doc = "/**\n"

    if class_name and not method_name:
        doc += f" * {class_name} class description.\n"
    else:
        doc += f" * {_extract_function_purpose('', method_name or class_name, 0)}\n"

    for param in params:
        doc += f" * @param {param} Description of {param}.\n"

    if method_name:
        doc += " * @return Description of return value.\n"

    doc += " */"

    return doc


def generate_documentation(source: str, language: str = "python", style: str = "google") -> dict[str, Any]:
    """Generate documentation for code.

    Supports:
    - Python: Google-style or NumPy-style docstrings
    - JavaScript: JSDoc format
    - Java: JavaDoc format
    - C#: XML documentation format
    """

    if language == "python":
        return _generate_python_docs(source, style)
    elif language == "javascript":
        return _generate_javascript_docs(source)
    elif language == "java":
        return _generate_java_docs(source)
    elif language == "csharp":
        return _generate_csharp_docs(source)
    else:
        return {
            "status": "unsupported",
            "message": f"Documentation generation not supported for {language}",
            "language": language,
        }


def _generate_python_docs(source: str, style: str = "google") -> dict[str, Any]:
    """Generate Python documentation."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {"status": "error", "message": "Could not parse Python code", "language": "python"}

    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private/magic methods if not interested
            if not node.name.startswith("_"):
                docstring = _generate_python_docstring(node, style)
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "type": "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                    "docstring": docstring,
                    "has_docstring": ast.get_docstring(node) is not None,
                })

        elif isinstance(node, ast.ClassDef):
            docstring = f'"""{node.name}.\n\nClass description.\n"""'
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "type": "class",
                "docstring": docstring,
                "has_docstring": ast.get_docstring(node) is not None,
            })

    missing_docs = len([f for f in functions if not f["has_docstring"]]) + len([c for c in classes if not c["has_docstring"]])

    return {
        "status": "success",
        "language": "python",
        "style": style,
        "summary": {
            "total_functions": len(functions),
            "total_classes": len(classes),
            "missing_docstrings": missing_docs,
        },
        "functions": functions,
        "classes": classes,
        "recommendations": _get_documentation_recommendations(functions, classes),
    }


def _generate_javascript_docs(source: str) -> dict[str, Any]:
    """Generate JavaScript documentation."""
    # Simple regex-based parsing for JavaScript
    func_pattern = r"(?:async\s+)?function\s+(\w+)\s*\((.*?)\)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>"

    functions = []
    for match in re.finditer(func_pattern, source):
        func_name = match.group(1) or match.group(3)
        params_str = match.group(2) or match.group(4)
        params = [p.strip() for p in params_str.split(",") if p.strip()]

        doc_obj = {"name": func_name, "params": params}
        jsdoc = _generate_jsdoc(doc_obj)

        functions.append({
            "name": func_name,
            "params": params,
            "line": source[:match.start()].count("\n") + 1,
            "docstring": jsdoc,
        })

    return {
        "status": "success",
        "language": "javascript",
        "summary": {
            "total_functions": len(functions),
            "missing_docstrings": len(functions),
        },
        "functions": functions,
        "recommendations": _get_documentation_recommendations(functions, []),
    }


def _generate_java_docs(source: str) -> dict[str, Any]:
    """Generate Java documentation."""
    # Simple regex-based parsing
    method_pattern = r"(public|private|protected)?\s*(static)?\s*(\w+)\s+(\w+)\s*\((.*?)\)"
    class_pattern = r"(public|private)?\s*class\s+(\w+)"

    classes = []
    for match in re.finditer(class_pattern, source):
        class_name = match.group(2)
        javadoc = _generate_javadoc(class_name=class_name)
        classes.append({
            "name": class_name,
            "type": "class",
            "docstring": javadoc,
        })

    methods = []
    for match in re.finditer(method_pattern, source):
        method_name = match.group(4)
        params_str = match.group(5)
        params = [p.strip().split()[-1] for p in params_str.split(",") if p.strip()]

        javadoc = _generate_javadoc(method_name=method_name, params=params)
        methods.append({
            "name": method_name,
            "params": params,
            "line": source[:match.start()].count("\n") + 1,
            "docstring": javadoc,
        })

    return {
        "status": "success",
        "language": "java",
        "summary": {
            "total_classes": len(classes),
            "total_methods": len(methods),
        },
        "classes": classes,
        "methods": methods,
        "recommendations": _get_documentation_recommendations(methods, classes),
    }


def _generate_csharp_docs(source: str) -> dict[str, Any]:
    """Generate C# XML documentation."""
    # Simple regex-based parsing
    method_pattern = r"(public|private|protected)?\s*(static)?\s*(\w+)\s+(\w+)\s*\((.*?)\)"

    methods = []
    for match in re.finditer(method_pattern, source):
        method_name = match.group(4)
        params_str = match.group(5)
        params = [p.strip().split()[-1] for p in params_str.split(",") if p.strip()]

        xml_doc = f"/// <summary>\n/// {_extract_function_purpose('', method_name, 0)}\n/// </summary>\n"
        for param in params:
            xml_doc += f"/// <param name=\"{param}\">Description of {param}</param>\n"
        xml_doc += "/// <returns>Description of return value</returns>"

        methods.append({
            "name": method_name,
            "params": params,
            "line": source[:match.start()].count("\n") + 1,
            "docstring": xml_doc,
        })

    return {
        "status": "success",
        "language": "csharp",
        "summary": {
            "total_methods": len(methods),
        },
        "methods": methods,
        "recommendations": _get_documentation_recommendations(methods, []),
    }


def _get_documentation_recommendations(functions: list[dict], classes: list[dict]) -> list[str]:
    """Generate documentation recommendations."""
    recommendations = []

    total_items = len(functions) + len(classes)
    if total_items == 0:
        recommendations.append("✓ No functions or classes found to document.")
        return recommendations

    missing = sum(1 for f in functions if not f.get("has_docstring", True)) + sum(1 for c in classes if not c.get("has_docstring", True))

    if missing > 0:
        recommendations.append(f"📝 {missing} items need documentation. Generated docstrings above.")
    else:
        recommendations.append("✓ All functions and classes are documented!")

    if len(functions) > 10:
        recommendations.append("💡 Consider breaking large modules into smaller ones for better maintainability.")

    if any("..." in f.get("docstring", "") for f in functions):
        recommendations.append("⚠️ Some generated docstrings have placeholders. Review and customize them.")

    return recommendations
