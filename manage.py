#!/usr/bin/env python
import os
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        from tools.build_frontend_bundles import build

        if build() != 0:
            raise SystemExit("Unable to build frontend bundles.")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
