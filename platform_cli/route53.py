"""Route53 zone and record management, scoped to zones this CLI created."""

import uuid

from botocore.exceptions import ClientError

from .aws import PlatformCliError
from .tags import build_tags, from_boto_tags, is_cli_managed, to_boto_tags


def _zone_id_only(zone_id: str) -> str:
    return zone_id.removeprefix("/hostedzone/")


def _get_zone_tags(route53, zone_id: str) -> dict:
    try:
        response = route53.list_tags_for_resource(ResourceType="hostedzone", ResourceId=zone_id)
    except ClientError as exc:
        raise PlatformCliError(str(exc)) from exc
    return from_boto_tags(response["ResourceTagSet"]["Tags"])


def _require_managed_zone(route53, zone_id: str, owner: str) -> None:
    tags = _get_zone_tags(route53, zone_id)
    if not is_cli_managed(tags) or tags.get("Owner") != owner:
        raise PlatformCliError(f"Zone '{zone_id}' was not created by this tool for owner '{owner}'.")


def create_zone(
    session,
    zone_name: str,
    owner: str,
    project: str = "platform-cli",
    environment: str = "dev",
) -> dict:
    route53 = session.client("route53")
    try:
        response = route53.create_hosted_zone(Name=zone_name, CallerReference=str(uuid.uuid4()))
    except ClientError as exc:
        raise PlatformCliError(f"Could not create zone '{zone_name}': {exc}") from exc

    zone_id = _zone_id_only(response["HostedZone"]["Id"])
    tags = build_tags(owner=owner, project=project, environment=environment)
    route53.change_tags_for_resource(ResourceType="hostedzone", ResourceId=zone_id, AddTags=to_boto_tags(tags))

    return {
        "ZoneId": zone_id,
        "Name": response["HostedZone"]["Name"],
        "NameServers": response["DelegationSet"]["NameServers"],
    }


def list_zones(session, owner: str) -> list[dict]:
    route53 = session.client("route53")
    result = []
    paginator = route53.get_paginator("list_hosted_zones")
    for page in paginator.paginate():
        for zone in page["HostedZones"]:
            zone_id = _zone_id_only(zone["Id"])
            try:
                tags = _get_zone_tags(route53, zone_id)
            except PlatformCliError:
                continue
            if is_cli_managed(tags) and tags.get("Owner") == owner:
                result.append({"ZoneId": zone_id, "Name": zone["Name"], "Owner": tags.get("Owner", "")})
    return result


def _change_record(session, zone_id: str, owner: str, action: str, name: str, record_type: str, values: list[str], ttl: int) -> dict:
    route53 = session.client("route53")
    zone_id = _zone_id_only(zone_id)
    _require_managed_zone(route53, zone_id, owner)

    try:
        route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": action,
                        "ResourceRecordSet": {
                            "Name": name,
                            "Type": record_type,
                            "TTL": ttl,
                            "ResourceRecords": [{"Value": value} for value in values],
                        },
                    }
                ]
            },
        )
    except ClientError as exc:
        raise PlatformCliError(str(exc)) from exc

    return {"ZoneId": zone_id, "Name": name, "Type": record_type, "Action": action}


def create_record(session, zone_id: str, owner: str, name: str, record_type: str, values: list[str], ttl: int = 300) -> dict:
    return _change_record(session, zone_id, owner, "CREATE", name, record_type, values, ttl)


def update_record(session, zone_id: str, owner: str, name: str, record_type: str, values: list[str], ttl: int = 300) -> dict:
    return _change_record(session, zone_id, owner, "UPSERT", name, record_type, values, ttl)


def delete_record(session, zone_id: str, owner: str, name: str, record_type: str) -> dict:
    route53 = session.client("route53")
    zone_id = _zone_id_only(zone_id)
    _require_managed_zone(route53, zone_id, owner)

    # Route53 DELETE requires the exact existing record (name/type/TTL/values) - fetch it
    # first so the caller only has to say *what* to delete, not repeat its current values.
    response = route53.list_resource_record_sets(HostedZoneId=zone_id, StartRecordName=name, StartRecordType=record_type, MaxItems="1")
    record_sets = response["ResourceRecordSets"]
    matches = record_sets and record_sets[0]["Name"].rstrip(".") == name.rstrip(".") and record_sets[0]["Type"] == record_type
    if not matches:
        raise PlatformCliError(f"Record '{name}' ({record_type}) not found in zone '{zone_id}'.")
    existing = record_sets[0]

    try:
        route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={"Changes": [{"Action": "DELETE", "ResourceRecordSet": existing}]},
        )
    except ClientError as exc:
        raise PlatformCliError(str(exc)) from exc

    return {"ZoneId": zone_id, "Name": name, "Type": record_type, "Action": "DELETE"}


def list_records(session, zone_id: str, owner: str) -> list[dict]:
    route53 = session.client("route53")
    zone_id = _zone_id_only(zone_id)
    _require_managed_zone(route53, zone_id, owner)

    records = []
    paginator = route53.get_paginator("list_resource_record_sets")
    for page in paginator.paginate(HostedZoneId=zone_id):
        for record_set in page["ResourceRecordSets"]:
            records.append(
                {
                    "Name": record_set["Name"],
                    "Type": record_set["Type"],
                    "TTL": record_set.get("TTL"),
                    "Values": [rr["Value"] for rr in record_set.get("ResourceRecords", [])],
                }
            )
    return records
