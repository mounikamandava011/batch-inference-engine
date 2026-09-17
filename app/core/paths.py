from pathlib import Path


class UnsafeInputPath(ValueError):
    pass


def resolve_input_file(root: Path, supplied: str) -> Path:
    raw = Path(supplied)

    if raw.is_absolute():
        raise UnsafeInputPath("absolute paths are not allowed")

    resolved_root = root.resolve()
    candidate = (resolved_root / raw).resolve()

    if not candidate.is_relative_to(resolved_root):
        raise UnsafeInputPath("input file escapes the configured input root")

    if not candidate.is_file():
        raise FileNotFoundError(supplied)

    return candidate
