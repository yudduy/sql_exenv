"""
Clean, minimal display module for CLI output.
Provides Claude Code-style formatting with spinners and tool call visualization.
"""

import sys
from contextlib import contextmanager
from typing import Any

from yaspin import yaspin
from yaspin.spinners import Spinners


class Display:
    """Centralized display manager for clean CLI output."""

    # ANSI color codes
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

    def __init__(self):
        self.current_spinner = None

    @contextmanager
    def spinner(self, status: str):
        """
        Display an animated spinner with status text.

        Usage:
            with display.spinner("Analyzing query..."):
                # do work
                pass
        """
        sp = yaspin(Spinners.dots, text=status, color="cyan")
        sp.start()
        try:
            yield sp
        finally:
            sp.stop()

    def tool_call(self, tool_name: str, params: dict[str, Any] | None = None):
        """
        Display a tool call in Claude Code style.

        Example output:
            ⚡ Using analyzer
              query: "SELECT * FROM users..."
              mode: "performance"
        """
        print(f"\n{self.CYAN}⚡ Using {tool_name}{self.RESET}")

        if params:
            for key, value in params.items():
                # Truncate long values
                str_value = str(value)
                if len(str_value) > 60:
                    str_value = str_value[:57] + "..."
                print(f"  {self.DIM}{key}: {str_value}{self.RESET}")

    def tool_result(self, tool_name: str, summary: str, details: str | None = None):
        """
        Display tool result.

        Example output:
            ✓ Analysis complete
              Found 3 optimization opportunities
        """
        print(f"{self.GREEN}✓ {summary}{self.RESET}")
        if details:
            for line in details.split('\n'):
                if line.strip():
                    print(f"  {self.DIM}{line}{self.RESET}")

    def info(self, message: str):
        """Display an info message."""
        print(f"{self.CYAN}ℹ {message}{self.RESET}")

    def success(self, message: str):
        """Display a success message."""
        print(f"{self.GREEN}✓ {message}{self.RESET}")

    def warning(self, message: str):
        """Display a warning message."""
        print(f"{self.YELLOW}⚠ {message}{self.RESET}")

    def error(self, message: str):
        """Display an error message."""
        print(f"{self.RED}✗ {message}{self.RESET}")

    def section(self, title: str, content: str, code_block: bool = False):
        """
        Display a markdown-style section.

        Args:
            title: Section title (will be styled as header)
            content: Section content
            code_block: If True, wraps content in SQL code block styling
        """
        print(f"\n{self.BOLD}{self.BLUE}## {title}{self.RESET}\n")

        if code_block:
            # Display as code block
            print(f"{self.DIM}```sql{self.RESET}")
            for line in content.split('\n'):
                print(f"{self.CYAN}{line}{self.RESET}")
            print(f"{self.DIM}```{self.RESET}\n")
        else:
            print(content)

    def header(self, text: str):
        """Display a header."""
        print(f"\n{self.BOLD}{self.BLUE}# {text}{self.RESET}\n")

    def subheader(self, text: str):
        """Display a subheader."""
        print(f"\n{self.BOLD}## {text}{self.RESET}\n")

    def code_block(self, code: str, language: str = "sql"):
        """Display a code block."""
        print(f"{self.DIM}```{language}{self.RESET}")
        for line in code.split('\n'):
            print(f"{self.CYAN}{line}{self.RESET}")
        print(f"{self.DIM}```{self.RESET}\n")

    def metric(self, label: str, value: str, improvement: str | None = None):
        """
        Display a metric with optional improvement indicator.

        Example:
            Execution time: 245ms → 12ms (95% faster)
        """
        if improvement:
            print(f"{self.DIM}{label}:{self.RESET} {value} {self.GREEN}{improvement}{self.RESET}")
        else:
            print(f"{self.DIM}{label}:{self.RESET} {value}")

    def divider(self):
        """Display a subtle divider (not a heavy separator)."""
        print(f"{self.DIM}{'─' * 50}{self.RESET}")

    def status_line(self, label: str, value: str, status: str = "success"):
        """
        Display a status line with colored indicator.

        Args:
            label: The label (e.g., "database", "connected")
            value: The value to display
            status: One of "success", "failure", "loading"
        """
        if status == "success":
            indicator = f"{self.GREEN}success{self.RESET}"
        elif status == "failure":
            indicator = f"{self.RED}failure{self.RESET}"
        elif status == "loading":
            indicator = f"{self.YELLOW}loading{self.RESET}"
        else:
            indicator = f"{self.DIM}{status}{self.RESET}"

        print(f"  {self.DIM}{label}:{self.RESET} {value} \\\\ {indicator}")

    def clear_line(self):
        """Clear the current line."""
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()

    def newline(self):
        """Print a blank line for spacing."""
        print()


# Global display instance
display = Display()
