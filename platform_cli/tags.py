"""Shared tagging convention for all CLI-created AWS resources."""

CREATED_BY_KEY = "CreatedBy"
CREATED_BY_VALUE = "platform-cli"


def build_tags(
    owner: str,
    project: str = "platform-cli",
    environment: str = "dev",
    extra: dict | None = None,
) -> dict:
    tags = {
        CREATED_BY_KEY: CREATED_BY_VALUE,
        "Owner": owner,
        "Project": project,
        "Environment": environment,
    }
    if extra:
        tags.update(extra)
    return tags


def to_boto_tags(tags: dict) -> list[dict]:
    return [{"Key": key, "Value": value} for key, value in tags.items()]


def from_boto_tags(boto_tags: list[dict]) -> dict:
    return {tag["Key"]: tag["Value"] for tag in boto_tags}


def is_cli_managed(tags: dict) -> bool:
    return tags.get(CREATED_BY_KEY) == CREATED_BY_VALUE
