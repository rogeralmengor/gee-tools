![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
[![CI Pipeline](https://github.com/rogeralmengor/gee-tools/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/rogeralmengor/gee-tools/actions/workflows/ci.yml)
[![Coverage Status](https://raw.githubusercontent.com/rogeralmengor/gee-tools/coverage-badges/badges/dev/coverage.svg)](https://github.com/rogeralmengor/gee-tools/actions/workflows/ci.yml)
![PyPI Version](https://img.shields.io/pypi/v/gee-tools.svg)
![License](https://img.shields.io/badge/license-MIT-green)

# GEE Tools Portfolio

A 6-month continuous integration project building, testing, and deploying Google Earth Engine (GEE) tools. 

## Project Philosophy
1. **LLM-Driven Development:** Tools are architected using the CROFTC prompt framework. Prompts are included in each tool's directory.
2. **Aggressive Testing:** Leveraging LLM-generated code to write comprehensive, cheap end-to-end and stress tests for geospatial infrastructure.
3. **Clean Code:** 100-character line limits (`ruff`), strict static typing (`mypy`), and self-documenting code structures over redundant docstrings.

## Stack
* **Python API:** Google Earth Engine
* **Dependency Management:** `uv`
* **CI/CD:** GitHub Actions
* **Environment:** Docker

## Running Locally
```bash
# Install dependencies using uv
uv pip install -e .[dev]

# Run tests
pytest tests/
