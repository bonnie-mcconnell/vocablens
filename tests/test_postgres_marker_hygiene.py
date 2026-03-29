from pathlib import Path


def test_postgres_harness_users_are_marker_tagged() -> None:
    tests_dir = Path(__file__).resolve().parent
    violating_files: list[str] = []

    for file_path in sorted(tests_dir.glob("test_*.py")):
        text = file_path.read_text(encoding="utf-8")
        if "postgres_harness(" not in text:
            continue
        if "pytest.mark.postgres" in text:
            continue
        violating_files.append(file_path.name)

    assert not violating_files, (
        "Any test module that uses postgres_harness must include the postgres marker: "
        + ", ".join(violating_files)
    )