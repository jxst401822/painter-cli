"""Pytest configuration shared across the test suite.

Adds skill scripts directories to sys.path so test modules can import them
as top-level modules (e.g. `import sugar_painting_gen`).
"""
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "skills",
        "sugar-painting-gen",
        "scripts",
    ),
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".import_bundle", "image-to-trajectory", "scripts"))
