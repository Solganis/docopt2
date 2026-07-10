"""A CLI with shell completion.

Usage:
  completion serve <host> [--port=<n>]
  completion build <target>

Options:
  --port=<n>  Port to bind [default: 8000].
"""

from docopt2 import generate_completion

# Print a shell-completion script for this program. Source it (bash/zsh/fish) or run it
# (PowerShell) to get context-aware Tab completion driven by the usage grammar above. Try:
#   python examples/completion.py > _completion.bash && source _completion.bash
if __name__ == "__main__":
    print(generate_completion(__doc__, prog="completion", shell="bash"))
