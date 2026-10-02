"""`python -m acme.distro_check`: the same entry point as the `distro-check` console script."""

from acme.distro_check.cli import main

raise SystemExit(main())
