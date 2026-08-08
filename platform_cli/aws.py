"""Shared AWS session handling for all resource modules."""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound


class PlatformCliError(Exception):
    """Expected, user-facing error (bad profile, quota exceeded, etc.)."""


def get_session(profile: str | None = None, region: str | None = None) -> boto3.Session:
    try:
        return boto3.Session(profile_name=profile, region_name=region)
    except ProfileNotFound as exc:
        raise PlatformCliError(
            f"AWS profile '{profile}' not found. Run 'aws configure --profile {profile}' first."
        ) from exc


def get_caller_username(session: boto3.Session) -> str:
    """Default Owner tag value: the IAM identity behind the session, not the local OS user."""
    try:
        identity = session.client("sts").get_caller_identity()
    except NoCredentialsError as exc:
        raise PlatformCliError(
            "No AWS credentials found. Pass a valid --profile, or run 'aws configure' "
            "to set up the default profile."
        ) from exc
    except ClientError as exc:
        raise PlatformCliError(f"Could not determine AWS identity: {exc}") from exc
    return identity["Arn"].rsplit("/", maxsplit=1)[-1]
