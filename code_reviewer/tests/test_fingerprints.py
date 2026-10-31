"""Regression tests for the cross-language proposal guard."""
import fingerprints
from tools import validate_candidate

# One representative sample per supported uploadable language.
SAMPLES = {
    "python": 'import os\n\n\ndef greet(name):\n    print(f"hello {name}")\n',
    "javascript": 'const fs = require("fs");\n\nfunction greet(name) {\n  console.log(`hello ${name}`);\n}\n\nmodule.exports = greet;\n',
    "java": 'package demo;\n\nimport java.util.List;\n\npublic class Greeter {\n    @Override\n    public String toString() {\n        return "hello";\n    }\n}\n',
    "csharp": 'using System;\n\nnamespace Demo\n{\n    public class Greeter\n    {\n        public static void Main(string[] args)\n        {\n            Console.WriteLine("hello");\n        }\n    }\n}\n',
    "c": '#include <stdio.h>\n\nint main(void) {\n    printf("hello\\n");\n    return 0;\n}\n',
    "cpp": '#include <iostream>\n#include <string>\n\nclass Greeter {\npublic:\n    ~Greeter() {}\n};\n\nint main() {\n    std::cout << "hello" << std::endl;\n    return 0;\n}\n',
}

# Plain C is valid C++ so a candidate written in C stays acceptable for a C++
# upload. The reverse direction is rejected, because C++ source is not valid C.
SUPERSET_ACCEPTANCES = {("cpp", "c")}


def test_every_supported_language_has_a_sample():
    assert set(SAMPLES) == set(fingerprints.LANGUAGE_ORDER)


def test_each_sample_is_detected_as_its_own_language():
    for language, sample in SAMPLES.items():
        report = fingerprints.fingerprint_report(sample)
        assert report["detected"] == language, f"{language} was detected as {report['detected']}"


def test_each_sample_is_accepted_for_its_own_language():
    for language, sample in SAMPLES.items():
        assert fingerprints.language_mismatch(sample, language) is None


def test_every_foreign_sample_is_rejected_for_every_language():
    """A proposal in one language must never pass for an upload in another."""
    for expected, expected_sample in SAMPLES.items():
        for language, sample in SAMPLES.items():
            if language == expected:
                continue
            message = fingerprints.language_mismatch(sample, expected)
            if (expected, language) in SUPERSET_ACCEPTANCES:
                # C source is valid C++ source, and JavaScript is valid
                # TypeScript, so the guard deliberately stays quiet here.
                assert message is None, f"{language} should stay acceptable for {expected}"
                continue
            assert message is not None, f"{language} was accepted for {expected}"
            assert "instead of" in message


def test_mismatch_message_names_the_expected_language():
    message = fingerprints.language_mismatch(SAMPLES["python"], "cpp")
    assert message is not None
    assert "Python-like" in message
    assert "C++" in message


def test_python_upload_rejects_a_cpp_candidate():
    message = fingerprints.language_mismatch(SAMPLES["cpp"], "python")
    assert message is not None
    assert "C++-like" in message
    assert "Python" in message


def test_javascript_upload_rejects_a_foreign_candidate():
    message = fingerprints.language_mismatch(SAMPLES["cpp"], "javascript")
    assert message is not None
    assert "C++-like" in message
    assert "JavaScript" in message


def test_unknown_language_is_not_reported_as_a_mismatch():
    assert fingerprints.language_mismatch(SAMPLES["python"], None) is None
    assert fingerprints.language_mismatch(SAMPLES["python"], "cobol") is None


def test_empty_candidate_is_not_reported_as_a_mismatch():
    assert fingerprints.language_mismatch("", "cpp") is None
    assert fingerprints.language_mismatch("   \n", "python") is None


def test_python_validation_rejects_a_foreign_candidate():
    valid, message, warnings = validate_candidate(
        SAMPLES["cpp"],
        "if True print('x')\n",
        language="python",
    )
    assert valid is False
    assert "C++-like" in message
    assert warnings == []


def test_python_validation_accepts_a_python_candidate():
    valid, message, _warnings = validate_candidate(
        "if True:\n    print('x')\n",
        "if True print('x')\n",
        language="python",
    )
    assert valid is True
    assert message == "Valid syntax"
