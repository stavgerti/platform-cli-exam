"""S3 bucket provisioning, scoped to buckets this CLI created."""

import json

from botocore.exceptions import ClientError

from .aws import PlatformCliError
from .tags import build_tags, from_boto_tags, is_cli_managed, to_boto_tags


def _get_bucket_tags(s3, bucket_name: str) -> dict:
    try:
        response = s3.get_bucket_tagging(Bucket=bucket_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchTagSet":
            return {}
        raise PlatformCliError(str(exc)) from exc
    return from_boto_tags(response["TagSet"])


def _require_managed_bucket(s3, bucket_name: str, owner: str) -> None:
    tags = _get_bucket_tags(s3, bucket_name)
    if not is_cli_managed(tags) or tags.get("Owner") != owner:
        raise PlatformCliError(f"Bucket '{bucket_name}' was not created by this tool for owner '{owner}'.")


def create_bucket(
    session,
    bucket_name: str,
    owner: str,
    project: str = "platform-cli",
    environment: str = "dev",
    public: bool = False,
    confirmed: bool = False,
) -> dict:
    if public and not confirmed:
        raise PlatformCliError(
            f"Creating public bucket '{bucket_name}' requires explicit confirmation."
        )

    s3 = session.client("s3")
    region = session.region_name

    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
    except ClientError as exc:
        raise PlatformCliError(f"Could not create bucket '{bucket_name}': {exc}") from exc

    s3.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )

    if public:
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/*",
                }
            ],
        }
        s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))
    else:
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )

    tags = build_tags(owner=owner, project=project, environment=environment)
    s3.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": to_boto_tags(tags)})

    return {"BucketName": bucket_name, "Public": public, "Region": region}


def upload_file(session, bucket_name: str, file_path: str, owner: str, key: str | None = None) -> dict:
    s3 = session.client("s3")
    _require_managed_bucket(s3, bucket_name, owner)

    object_key = key or file_path.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]
    try:
        s3.upload_file(file_path, bucket_name, object_key)
    except ClientError as exc:
        raise PlatformCliError(f"Could not upload '{file_path}' to '{bucket_name}': {exc}") from exc

    return {"BucketName": bucket_name, "Key": object_key}


def list_buckets(session, owner: str) -> list[dict]:
    s3 = session.client("s3")
    all_buckets = s3.list_buckets()["Buckets"]

    result = []
    for bucket in all_buckets:
        name = bucket["Name"]
        try:
            tags = _get_bucket_tags(s3, name)
        except PlatformCliError:
            # Can't read tags (no permission, explicit deny, etc.) -> can't confirm it's
            # ours, so treat it the same as "not managed by this tool" and move on.
            continue
        if is_cli_managed(tags) and tags.get("Owner") == owner:
            result.append(
                {
                    "BucketName": name,
                    "Owner": tags.get("Owner", ""),
                    "Project": tags.get("Project", ""),
                    "CreationDate": bucket["CreationDate"].isoformat(),
                }
            )
    return result
