"""Command-line entry point for new models and saved-output reproduction."""
from benchmark.runner import main

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        # Credential values are never included in configuration/transport errors.
        print('ERROR:', str(exc))
        raise SystemExit(2)
