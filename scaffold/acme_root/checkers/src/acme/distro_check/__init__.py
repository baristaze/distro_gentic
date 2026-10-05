"""distro-check: the static checker of the distro_gentic spec's lenses.

It decides the parts of the platform's lenses a parser can decide
without guessing, by reading a project's source with `ast`. It never
imports the code it checks. Standard library only.

It sits beside the engine's checker, `acme.agentic_check`, and runs on
its framework: the parsed project, the rule and finding values, and the
runner come from there. What is the platform's own is here: its lens
catalog, its registry, its configuration table, its command line, and
its rules.

`__version__` is the platform release this checker ships with, which the
platform's `scripts/check_version.py` holds equal to its plugin manifest.
"""

__version__ = "0.4.0"
