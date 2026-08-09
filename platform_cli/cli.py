"""Click-based CLI entrypoint wiring ec2/s3/route53 into one tool."""

from functools import wraps

import click

from . import ec2, route53, s3
from .aws import PlatformCliError, get_caller_username, get_session


def handle_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PlatformCliError as exc:
            raise click.ClickException(str(exc))

    return wrapper


def _context(ctx):
    obj = ctx.obj
    session = get_session(profile=obj["profile"], region=obj["region"])
    owner = obj["owner"] or get_caller_username(session)
    return session, owner, obj["project"], obj["environment"]


@click.group()
@click.option("--profile", default=None, help="AWS profile to use (defaults to the 'default' profile).")
@click.option("--region", default=None, help="AWS region (defaults to the profile's configured region).")
@click.option("--owner", default=None, help="Owner tag value (defaults to your AWS identity).")
@click.option("--project", default="platform-cli", show_default=True, help="Project tag value.")
@click.option("--environment", default="dev", show_default=True, help="Environment tag value.")
@click.pass_context
def cli(ctx, profile, region, owner, project, environment):
    """Self-service CLI for provisioning AWS EC2, S3, and Route53 resources within guardrails."""
    ctx.ensure_object(dict)
    ctx.obj.update(profile=profile, region=region, owner=owner, project=project, environment=environment)


# ---------- EC2 ----------


@cli.group("ec2")
def ec2_group():
    """Manage EC2 instances created by this tool."""


@ec2_group.command("create")
@click.option(
    "--instance-type",
    default="t3.micro",
    show_default=True,
    type=click.Choice(sorted(ec2.ALLOWED_INSTANCE_TYPES)),
    help="EC2 instance type.",
)
@click.option(
    "--os-family",
    default="ubuntu",
    show_default=True,
    type=click.Choice(sorted(ec2.AMI_SSM_PARAMS)),
    help="OS family used to look up the latest AMI via SSM.",
)
@click.option("--name", default=None, help="Optional Name tag for the instance.")
@click.pass_context
@handle_errors
def ec2_create(ctx, instance_type, os_family, name):
    """Create an EC2 instance (capped at 2 running instances per owner)."""
    session, owner, project, environment = _context(ctx)
    result = ec2.create_instance(
        session,
        owner=owner,
        project=project,
        environment=environment,
        instance_type=instance_type,
        os_family=os_family,
        name=name,
    )
    click.secho(
        f"Created instance {result['InstanceId']} (state={result['State']}, type={result['InstanceType']})",
        fg="green",
    )


@ec2_group.command("start")
@click.option("--instance-id", required=True)
@click.pass_context
@handle_errors
def ec2_start(ctx, instance_id):
    """Start a CLI-created EC2 instance."""
    session, owner, _, _ = _context(ctx)
    ec2.start_instance(session, instance_id, owner)
    click.secho(f"Started instance {instance_id}", fg="green")


@ec2_group.command("stop")
@click.option("--instance-id", required=True)
@click.pass_context
@handle_errors
def ec2_stop(ctx, instance_id):
    """Stop a CLI-created EC2 instance."""
    session, owner, _, _ = _context(ctx)
    ec2.stop_instance(session, instance_id, owner)
    click.secho(f"Stopped instance {instance_id}", fg="green")


@ec2_group.command("terminate")
@click.option("--instance-id", required=True)
@click.pass_context
@handle_errors
def ec2_terminate(ctx, instance_id):
    """Permanently terminate a CLI-created EC2 instance."""
    session, owner, _, _ = _context(ctx)
    confirmed = click.confirm(f"Instance '{instance_id}' will be PERMANENTLY TERMINATED. Are you sure?", default=False)
    if not confirmed:
        click.echo("Aborted.")
        return
    ec2.terminate_instance(session, instance_id, owner, confirmed=confirmed)
    click.secho(f"Terminated instance {instance_id}", fg="green")


@ec2_group.command("list")
@click.pass_context
@handle_errors
def ec2_list(ctx):
    """List EC2 instances created by this tool for the current owner."""
    session, owner, _, _ = _context(ctx)
    instances = ec2.list_instances(session, owner)
    if not instances:
        click.echo("No EC2 instances found.")
        return
    for inst in instances:
        click.echo(
            f"{inst['InstanceId']}  {inst['State']:10}  {inst['InstanceType']:10}  "
            f"{inst['Name']:20}  owner={inst['Owner']}"
        )


# ---------- S3 ----------


@cli.group("s3")
def s3_group():
    """Manage S3 buckets created by this tool."""


@s3_group.command("create")
@click.option("--bucket-name", required=True, help="Globally-unique S3 bucket name.")
@click.option("--public", is_flag=True, default=False, help="Make the bucket publicly readable.")
@click.pass_context
@handle_errors
def s3_create(ctx, bucket_name, public):
    """Create an S3 bucket (private + encrypted by default)."""
    session, owner, project, environment = _context(ctx)

    confirmed = True
    if public:
        confirmed = click.confirm(f"Bucket '{bucket_name}' will be PUBLIC. Are you sure?", default=False)
        if not confirmed:
            click.echo("Aborted.")
            return

    result = s3.create_bucket(
        session, bucket_name, owner=owner, project=project, environment=environment, public=public, confirmed=confirmed
    )
    click.secho(
        f"Created bucket {result['BucketName']} (public={result['Public']}, region={result['Region']})", fg="green"
    )


@s3_group.command("upload")
@click.option("--bucket-name", required=True)
@click.option(
    "--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False), help="Local file to upload."
)
@click.option("--key", default=None, help="Destination object key (defaults to the file name).")
@click.pass_context
@handle_errors
def s3_upload(ctx, bucket_name, file_path, key):
    """Upload a file to a CLI-created bucket."""
    session, owner, _, _ = _context(ctx)
    result = s3.upload_file(session, bucket_name, file_path, owner=owner, key=key)
    click.secho(f"Uploaded to s3://{result['BucketName']}/{result['Key']}", fg="green")


@s3_group.command("delete")
@click.option("--bucket-name", required=True)
@click.pass_context
@handle_errors
def s3_delete(ctx, bucket_name):
    """Permanently delete a CLI-created S3 bucket (must be empty)."""
    session, owner, _, _ = _context(ctx)
    confirmed = click.confirm(f"Bucket '{bucket_name}' will be PERMANENTLY DELETED. Are you sure?", default=False)
    if not confirmed:
        click.echo("Aborted.")
        return
    s3.delete_bucket(session, bucket_name, owner, confirmed=confirmed)
    click.secho(f"Deleted bucket {bucket_name}", fg="green")


@s3_group.command("list")
@click.pass_context
@handle_errors
def s3_list(ctx):
    """List S3 buckets created by this tool for the current owner."""
    session, owner, _, _ = _context(ctx)
    buckets = s3.list_buckets(session, owner)
    if not buckets:
        click.echo("No S3 buckets found.")
        return
    for bucket in buckets:
        click.echo(f"{bucket['BucketName']:40}  created={bucket['CreationDate']}  owner={bucket['Owner']}")


# ---------- Route53 ----------


@cli.group("route53")
def route53_group():
    """Manage Route53 zones and records created by this tool."""


@route53_group.command("create-zone")
@click.option("--zone-name", required=True, help="DNS zone name, e.g. example.com.")
@click.pass_context
@handle_errors
def route53_create_zone(ctx, zone_name):
    """Create a hosted zone."""
    session, owner, project, environment = _context(ctx)
    result = route53.create_zone(session, zone_name, owner=owner, project=project, environment=environment)
    click.secho(f"Created zone {result['ZoneId']} ({result['Name']})", fg="green")
    for name_server in result["NameServers"]:
        click.echo(f"  NS: {name_server}")


@route53_group.command("list-zones")
@click.pass_context
@handle_errors
def route53_list_zones(ctx):
    """List hosted zones created by this tool for the current owner."""
    session, owner, _, _ = _context(ctx)
    zones = route53.list_zones(session, owner)
    if not zones:
        click.echo("No Route53 zones found.")
        return
    for zone in zones:
        click.echo(f"{zone['ZoneId']:24}  {zone['Name']:40}  owner={zone['Owner']}")


@route53_group.command("create-record")
@click.option("--zone-id", required=True)
@click.option("--name", required=True)
@click.option("--type", "record_type", required=True, help="Record type, e.g. A, CNAME, TXT.")
@click.option("--value", "values", multiple=True, required=True, help="Record value; repeat for multiple values.")
@click.option("--ttl", default=300, show_default=True)
@click.pass_context
@handle_errors
def route53_create_record(ctx, zone_id, name, record_type, values, ttl):
    """Create a DNS record in a CLI-created zone."""
    session, owner, _, _ = _context(ctx)
    result = route53.create_record(session, zone_id, owner, name, record_type, list(values), ttl)
    click.secho(f"Created record {result['Name']} ({result['Type']})", fg="green")


@route53_group.command("update-record")
@click.option("--zone-id", required=True)
@click.option("--name", required=True)
@click.option("--type", "record_type", required=True)
@click.option("--value", "values", multiple=True, required=True)
@click.option("--ttl", default=300, show_default=True)
@click.pass_context
@handle_errors
def route53_update_record(ctx, zone_id, name, record_type, values, ttl):
    """Update (upsert) a DNS record in a CLI-created zone."""
    session, owner, _, _ = _context(ctx)
    result = route53.update_record(session, zone_id, owner, name, record_type, list(values), ttl)
    click.secho(f"Updated record {result['Name']} ({result['Type']})", fg="green")


@route53_group.command("delete-record")
@click.option("--zone-id", required=True)
@click.option("--name", required=True)
@click.option("--type", "record_type", required=True)
@click.pass_context
@handle_errors
def route53_delete_record(ctx, zone_id, name, record_type):
    """Delete a DNS record from a CLI-created zone."""
    session, owner, _, _ = _context(ctx)
    result = route53.delete_record(session, zone_id, owner, name, record_type)
    click.secho(f"Deleted record {result['Name']} ({result['Type']})", fg="green")


@route53_group.command("list-records")
@click.option("--zone-id", required=True)
@click.pass_context
@handle_errors
def route53_list_records(ctx, zone_id):
    """List DNS records in a CLI-created zone."""
    session, owner, _, _ = _context(ctx)
    records = route53.list_records(session, zone_id, owner)
    for record in records:
        click.echo(f"{record['Name']:40}  {record['Type']:6}  ttl={record['TTL']}  {', '.join(record['Values'])}")


if __name__ == "__main__":
    cli()
