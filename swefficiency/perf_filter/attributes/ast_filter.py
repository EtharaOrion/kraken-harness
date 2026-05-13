# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AST-based change validation for Stage II Criterion 3.

Paper specification (Appendix C.2):
  "select more specifically for substantial performance related changes,
   which are almost guaranteed to require a modification to a code file's AST."

Implementation:
  - Primary: Use tree-sitter-python to parse changed hunks
  - Fallback: Regex-based heuristic if tree-sitter unavailable
  
  A change is considered "meaningful to AST" if it modifies something other than:
  - Comments (# lines)
  - Docstrings (triple-quoted strings at statement level)
  - Whitespace/formatting
  - Type annotations only (debatable, included for now)
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import tree-sitter; graceful fallback if unavailable
_TREE_SITTER_AVAILABLE = False
try:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser

    _TREE_SITTER_AVAILABLE = True
    _PY_LANGUAGE = Language(tspython.language())
    _parser = Parser(_PY_LANGUAGE)
    logger.debug("tree-sitter-python available, using AST-based validation")
except ImportError:
    logger.info(
        "tree-sitter-python not installed. Using regex fallback for AST validation. "
        "Install with: pip install tree-sitter tree-sitter-python"
    )


def has_meaningful_ast_changes(patch: str) -> bool:
    """
    Check if a patch contains changes that would modify the AST.
    
    Returns True if at least one file in the patch has non-trivial code changes
    (not just comments, docstrings, or whitespace).
    
    Returns True by default for non-Python files (conservative — don't reject).
    """
    if not patch or not patch.strip():
        return False

    # Extract added/removed lines from hunks
    hunks = _extract_change_hunks(patch)
    
    if not hunks:
        return False

    # Check each file's changes
    for file_path, added_lines, removed_lines in hunks:
        # Only validate Python files — non-Python changes are assumed meaningful
        if not file_path.endswith(".py"):
            return True

        # Check if changes are meaningful
        if _TREE_SITTER_AVAILABLE:
            if _has_meaningful_changes_treesitter(added_lines, removed_lines):
                return True
        else:
            if _has_meaningful_changes_heuristic(added_lines, removed_lines):
                return True

    return False


def _extract_change_hunks(patch: str) -> list[tuple[str, list[str], list[str]]]:
    """Extract (file_path, added_lines, removed_lines) from unified diff.
    
    Only extracts the actual +/- lines from hunks, ignoring context lines.
    """
    results = []
    
    split_by_diff = patch.split("diff --git")
    
    for diff_section in split_by_diff[1:]:
        lines = diff_section.split("\n")
        if not lines:
            continue
            
        # Parse file path from header
        header = lines[0].strip()
        parts = header.split()
        if len(parts) < 2:
            continue
        dest_path = parts[-1]
        if dest_path.startswith("b/"):
            dest_path = dest_path[2:]
        
        # Extract added and removed lines from hunks
        added = []
        removed = []
        in_hunk = False
        
        for line in lines[1:]:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])  # Strip the leading +
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])  # Strip the leading -
        
        if added or removed:
            results.append((dest_path, added, removed))
    
    return results


def _has_meaningful_changes_treesitter(
    added_lines: list[str], removed_lines: list[str]
) -> bool:
    """Use tree-sitter to check if changed lines contain AST-meaningful content.
    
    Strategy: Parse the added/removed lines as Python code snippets.
    If any parsed node is NOT a comment or string_content at expression_statement level,
    the change is meaningful.
    """
    for lines in [added_lines, removed_lines]:
        meaningful = _filter_meaningful_lines(lines)
        if meaningful:
            # Try to parse as Python — if it has real code nodes, it's meaningful
            code = "\n".join(meaningful)
            try:
                tree = _parser.parse(bytes(code, "utf8"))
                root = tree.root_node
                if _tree_has_code_nodes(root):
                    return True
            except Exception:
                # If parsing fails, the lines are probably partial code — assume meaningful
                return True
    
    return False


def _tree_has_code_nodes(node) -> bool:
    """Check if a tree-sitter parse tree contains actual code (not just comments/strings)."""
    # Types that are NOT meaningful changes
    non_meaningful_types = {"comment", "expression_statement"}
    
    for child in node.children:
        if child.type == "comment":
            continue
        if child.type == "expression_statement":
            # Check if it's just a string literal (docstring)
            if len(child.children) == 1 and child.children[0].type in ("string", "concatenated_string"):
                continue
            # It's a real expression statement (function call, assignment, etc.)
            return True
        if child.type == "ERROR":
            # Parse error — likely partial code, assume meaningful
            return True
        # Any other node type is meaningful code
        if child.type not in ("module",):
            return True
    
    return False


def _has_meaningful_changes_heuristic(
    added_lines: list[str], removed_lines: list[str]
) -> bool:
    """Regex-based fallback when tree-sitter is not available.
    
    Checks if changed lines contain more than just:
    - Blank lines
    - Comment lines (# ...)
    - Docstring lines (triple quotes, or lines inside triple-quoted blocks)
    - Pure whitespace changes
    """
    for lines in [added_lines, removed_lines]:
        meaningful = _filter_meaningful_lines(lines)
        if meaningful:
            return True
    
    return False


# Regex patterns for non-meaningful lines
_BLANK_RE = re.compile(r"^\s*$")
_COMMENT_RE = re.compile(r"^\s*#")
_DOCSTRING_OPEN_RE = re.compile(r'^\s*("""|\'\'\')')
_DOCSTRING_SINGLE_RE = re.compile(r'^\s*(""".*"""|\'\'\'.*\'\'\')(\s*#.*)?$')


def _filter_meaningful_lines(lines: list[str]) -> list[str]:
    """Filter out comments, blank lines, and docstrings. Return lines with real code."""
    meaningful = []
    in_docstring = False
    docstring_marker: Optional[str] = None
    
    for line in lines:
        # Skip blank lines
        if _BLANK_RE.match(line):
            continue
        
        # Handle docstring state
        if in_docstring:
            if docstring_marker and docstring_marker in line:
                in_docstring = False
                docstring_marker = None
            continue
        
        # Check for docstring start
        if _DOCSTRING_SINGLE_RE.match(line):
            # Single-line docstring like: """This is a docstring."""
            continue
        
        ds_match = _DOCSTRING_OPEN_RE.match(line)
        if ds_match:
            marker = ds_match.group(1)
            # Check if it closes on the same line (already handled above)
            # Otherwise, start multi-line docstring
            rest_of_line = line[line.index(marker) + 3:]
            if marker not in rest_of_line:
                in_docstring = True
                docstring_marker = marker
            continue
        
        # Skip comment-only lines
        if _COMMENT_RE.match(line):
            continue
        
        # This line has actual code
        meaningful.append(line)
    
    return meaningful


def is_tree_sitter_available() -> bool:
    """Check if tree-sitter is available for AST-based validation."""
    return _TREE_SITTER_AVAILABLE
