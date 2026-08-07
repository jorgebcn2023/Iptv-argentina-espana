# Deprecated: this file kept for backwards compatibility.
# Use the root-level main.py instead.

if __name__ == "__main__":
    from pathlib import Path
    import sys
    # ensure repository root is on sys.path
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from main import main
    main()
