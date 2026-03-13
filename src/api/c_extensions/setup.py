"""
Root setup.py — handles C extension compilation with platform-aware flags.
All package metadata lives in pyproject.toml; this file exists solely to
define the ext_modules that pyproject.toml can't express conditionally.

    pip install -e .                  # builds extension automatically
    python setup.py build_ext --inplace   # manual rebuild during development
"""

import sys

from setuptools import Extension, setup

if sys.platform == "win32":
    compile_args = ["/O2", "/W3"]
else:
    compile_args = ["-O3", "-std=c11", "-Wall", "-Wno-unused-parameter"]

ext = Extension(
    name="delta_normalizer_core",
    sources=["src/api/c_extensions/delta_normalizer_core.c"],
    extra_compile_args=compile_args,
)

setup(ext_modules=[ext])
