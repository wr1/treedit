"""Makefile targets for the tree's Make menu (no make involved)."""

from treedit.makefile import is_makefile, parse_targets


def test_is_makefile():
    assert is_makefile("Makefile") and is_makefile("pkg/GNUmakefile")
    assert is_makefile("build.mk") and is_makefile("dir/common.make")
    assert not is_makefile("Makefile.am") and not is_makefile("readme.md")
    assert not is_makefile("makefile.txt")


def test_targets_in_order_with_descriptions_and_default_goal():
    text = """\
ROOT ?= .
.DEFAULT_GOAL := test
.PHONY: help test
help:
\t@echo help
test lint: pkg ## Run the checks
\t@true
$(VENV)/bin/tool: pyproject.toml
foo%: ; @true
install: ## Install
"""
    assert parse_targets(text) == [
        {"name": "help", "desc": "", "default": False},
        {"name": "test", "desc": "Run the checks", "default": True},
        {"name": "lint", "desc": "Run the checks", "default": False},
        {"name": "install", "desc": "Install", "default": False},
    ]


def test_first_rule_is_default_and_groups_are_split():
    text = """\
all build: ## Build everything
\t@true
clean:
\trm -rf out
"""
    assert parse_targets(text) == [
        {"name": "all", "desc": "Build everything", "default": True},
        {"name": "build", "desc": "Build everything", "default": False},
        {"name": "clean", "desc": "", "default": False},
    ]


def test_continuations_comments_and_duplicates():
    text = """\
# a comment
long: one \\
      two
long: ## The full description
other: # a plain comment
\t@true
# trailing
"""
    assert parse_targets(text) == [
        {"name": "long", "desc": "The full description", "default": True},
        {"name": "other", "desc": "", "default": False},
    ]
    assert parse_targets("") == []
