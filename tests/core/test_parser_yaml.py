"""Tests for the YAML parser."""

from __future__ import annotations

import pytest

from axon.core.parsers.yaml_lang import YamlParser


@pytest.fixture
def parser() -> YamlParser:
    return YamlParser()


def test_parse_yaml_kubernetes_manifest(parser: YamlParser) -> None:
    code = """\
kind: Deployment
metadata:
  name: web
spec:
  replicas: 2
"""
    result = parser.parse(code, "infra/deployment.yaml")

    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.name == "Deployment/web"
    assert symbol.kind == "class"
    assert symbol.start_line == 1
    assert symbol.end_line == 5


def test_parse_yaml_multiple_documents(parser: YamlParser) -> None:
    code = """\
---
kind: Service
metadata:
  name: api
---
kind: Deployment
metadata:
  name: api
"""
    result = parser.parse(code, "infra/stack.yaml")
    names = [symbol.name for symbol in result.symbols]

    assert names == ["Service/api", "Deployment/api"]


def test_parse_yaml_non_kubernetes_fallback(parser: YamlParser) -> None:
    code = """\
name: Deploy
on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
"""
    result = parser.parse(code, ".github/workflows/ci.yaml")

    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.name == "document_1:name"
    assert symbol.kind == "type_alias"
