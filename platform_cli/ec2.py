"""EC2 instance provisioning, scoped to instances this CLI created."""

from botocore.exceptions import ClientError

from .aws import PlatformCliError
from .tags import CREATED_BY_KEY, CREATED_BY_VALUE, build_tags, from_boto_tags, is_cli_managed, to_boto_tags

ALLOWED_INSTANCE_TYPES = {"t3.micro", "t2.small"}
RUNNING_INSTANCE_CAP = 2

AMI_SSM_PARAMS = {
    "ubuntu": "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id",
    "amazon-linux": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
}


def get_latest_ami(session, os_family: str) -> str:
    if os_family not in AMI_SSM_PARAMS:
        raise PlatformCliError(
            f"Unsupported os_family '{os_family}'. Choose from: {', '.join(AMI_SSM_PARAMS)}"
        )
    ssm = session.client("ssm")
    parameter = ssm.get_parameter(Name=AMI_SSM_PARAMS[os_family])
    return parameter["Parameter"]["Value"]


def _owner_scope_filters(owner: str) -> list[dict]:
    """CreatedBy scopes to this tool; Owner scopes to this user - needed because AWS
    accounts (e.g. a shared classroom account) can hold other students' platform-cli
    resources tagged with the same CreatedBy value."""
    return [
        {"Name": f"tag:{CREATED_BY_KEY}", "Values": [CREATED_BY_VALUE]},
        {"Name": "tag:Owner", "Values": [owner]},
    ]


def _count_running_cli_instances(ec2, owner: str) -> int:
    # "pending" counts too: a just-launched instance hasn't reached "running" yet but
    # already occupies a slot - without this, rapid creates can race past the cap.
    response = ec2.describe_instances(
        Filters=_owner_scope_filters(owner) + [{"Name": "instance-state-name", "Values": ["pending", "running"]}]
    )
    return sum(len(reservation["Instances"]) for reservation in response["Reservations"])


def _get_managed_instance(ec2, instance_id: str, owner: str) -> dict:
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
    except ClientError as exc:
        raise PlatformCliError(str(exc)) from exc

    reservations = response["Reservations"]
    if not reservations:
        raise PlatformCliError(f"Instance '{instance_id}' not found.")

    instance = reservations[0]["Instances"][0]
    tags = from_boto_tags(instance.get("Tags", []))
    if not is_cli_managed(tags) or tags.get("Owner") != owner:
        raise PlatformCliError(f"Instance '{instance_id}' was not created by this tool for owner '{owner}'.")
    return instance


def create_instance(
    session,
    owner: str,
    project: str = "platform-cli",
    environment: str = "dev",
    instance_type: str = "t3.micro",
    os_family: str = "ubuntu",
    name: str | None = None,
) -> dict:
    if instance_type not in ALLOWED_INSTANCE_TYPES:
        raise PlatformCliError(
            f"Instance type '{instance_type}' not allowed. Choose from: {', '.join(ALLOWED_INSTANCE_TYPES)}"
        )

    ec2 = session.client("ec2")
    running = _count_running_cli_instances(ec2, owner)
    if running >= RUNNING_INSTANCE_CAP:
        raise PlatformCliError(
            f"Cannot create instance: {running} CLI-created instances are already running "
            f"(limit is {RUNNING_INSTANCE_CAP})."
        )

    ami_id = get_latest_ami(session, os_family)
    tags = build_tags(owner=owner, project=project, environment=environment, extra={"Name": name} if name else None)

    # Root device name differs by AMI family (Ubuntu: /dev/sda1, Amazon Linux
    # 2023: /dev/xvda) - ask the AMI itself instead of hardcoding one.
    root_device_name = ec2.describe_images(ImageIds=[ami_id])["Images"][0]["RootDeviceName"]

    response = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{"ResourceType": "instance", "Tags": to_boto_tags(tags)}],
        BlockDeviceMappings=[
            {
                "DeviceName": root_device_name,
                "Ebs": {"Encrypted": True, "VolumeType": "gp3"},
            }
        ],
    )
    instance = response["Instances"][0]
    return {
        "InstanceId": instance["InstanceId"],
        "State": instance["State"]["Name"],
        "InstanceType": instance["InstanceType"],
        "ImageId": instance["ImageId"],
    }


def start_instance(session, instance_id: str, owner: str) -> dict:
    ec2 = session.client("ec2")
    instance = _get_managed_instance(ec2, instance_id, owner)

    # The cap is an invariant ("never more than 2 running"), not a one-time check at
    # create time - otherwise stop+create+start could sneak past it.
    if instance["State"]["Name"] not in ("pending", "running"):
        running = _count_running_cli_instances(ec2, owner)
        if running >= RUNNING_INSTANCE_CAP:
            raise PlatformCliError(
                f"Cannot start instance: {running} CLI-created instances are already running "
                f"(limit is {RUNNING_INSTANCE_CAP})."
            )

    ec2.start_instances(InstanceIds=[instance_id])
    return {"InstanceId": instance_id, "Action": "start"}


def stop_instance(session, instance_id: str, owner: str) -> dict:
    ec2 = session.client("ec2")
    _get_managed_instance(ec2, instance_id, owner)
    ec2.stop_instances(InstanceIds=[instance_id])
    return {"InstanceId": instance_id, "Action": "stop"}


def list_instances(session, owner: str) -> list[dict]:
    ec2 = session.client("ec2")
    response = ec2.describe_instances(Filters=_owner_scope_filters(owner))
    instances = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            tags = from_boto_tags(instance.get("Tags", []))
            instances.append(
                {
                    "InstanceId": instance["InstanceId"],
                    "State": instance["State"]["Name"],
                    "InstanceType": instance["InstanceType"],
                    "Name": tags.get("Name", ""),
                    "Owner": tags.get("Owner", ""),
                }
            )
    return instances
