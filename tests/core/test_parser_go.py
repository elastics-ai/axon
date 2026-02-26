"""Tests for the Go parser."""

from __future__ import annotations

import pytest

from axon.core.parsers.go_lang import GoParser


@pytest.fixture
def parser() -> GoParser:
    return GoParser()


def test_parse_go_symbols(parser: GoParser) -> None:
    code = """\
package service

type Service struct{}

func NewService(name string) *Service {
    return &Service{}
}

func (s *Service) Run(ctx Context) error {
    return nil
}
"""
    result = parser.parse(code, "service.go")

    classes = [s for s in result.symbols if s.kind == "class"]
    functions = [s for s in result.symbols if s.kind == "function"]
    methods = [s for s in result.symbols if s.kind == "method"]

    assert len(classes) == 1
    assert classes[0].name == "Service"

    assert len(functions) == 1
    assert functions[0].name == "NewService"

    assert len(methods) == 1
    assert methods[0].name == "Run"
    assert methods[0].class_name == "Service"


def test_parse_go_imports(parser: GoParser) -> None:
    code = """\
package app

import (
    "fmt"
    db "project/internal/db"
    . "project/internal/helpers"
    _ "unsafe"
)
"""
    result = parser.parse(code, "main.go")

    assert len(result.imports) == 4

    by_module = {imp.module: imp for imp in result.imports}
    assert by_module["fmt"].names == []
    assert by_module["project/internal/db"].names == ["db"]
    assert by_module["project/internal/db"].alias == "db"
    assert by_module["project/internal/helpers"].names == []
    assert by_module["unsafe"].names == []


def test_parse_go_calls(parser: GoParser) -> None:
    code = """\
package app

import "fmt"

func run(ctx Context) {
    fmt.Println(ctx)
    helper(ctx)
}
"""
    result = parser.parse(code, "run.go")

    print_calls = [c for c in result.calls if c.name == "Println"]
    helper_calls = [c for c in result.calls if c.name == "helper"]

    assert len(print_calls) == 1
    assert print_calls[0].receiver == "fmt"

    assert len(helper_calls) == 1
    assert helper_calls[0].receiver == ""


def test_parse_go_type_refs(parser: GoParser) -> None:
    code = """\
package app

import "project/internal/db"

type User struct {
    Client *db.Client
    Name string
}

type Runner interface {
    Run(ctx Context) error
    io.Reader
}

type UserMap = map[string]User

func Build(user User, ctx Context) (*Result, error) {
    var repo Repo
    return nil, nil
}
"""
    result = parser.parse(code, "types.go")

    type_names = {t.name for t in result.type_refs}
    assert "Client" in type_names
    assert "Reader" in type_names
    assert "User" in type_names
    assert "Context" in type_names
    assert "Result" in type_names
    assert "Repo" in type_names
    assert "string" not in type_names
    assert "error" not in type_names


def test_parse_go_exports(parser: GoParser) -> None:
    code = """\
package app

type service struct{}
type Service struct{}

func run() {}
func Run() {}
"""
    result = parser.parse(code, "exports.go")

    assert "Service" in result.exports
    assert "Run" in result.exports
    assert "service" not in result.exports
    assert "run" not in result.exports
