# platform-cli

A self-service CLI for provisioning AWS resources (EC2, S3, Route53) within
pre-defined guardrails, so developers don't need AWS console access or
platform-team hand-holding to get a dev instance, a bucket, or a DNS record.

Every resource it touches is scoped by tags — the tool only ever creates,
lists, or modifies resources it created itself, for the identity running it.
This makes it safe to run against a **shared AWS account**: it won't see or
touch resources created by other users of the tool.

## Prerequisites

- Python 3.10+
- An AWS account with an IAM user/role that has permissions for EC2, S3,
  Route53, SSM (read-only, for AMI lookups), and STS (`GetCallerIdentity`)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  installed, with a configured profile:

  ```bash
  aws configure --profile platform-cli-exam
  ```

  No credentials are ever stored in this repo — the tool only reads
  whatever profile you point it at.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
pip install -e .
```

The last command registers the `platform-cli` command on your PATH. Without
it, every example below also works as `python -m platform_cli.cli ...`.

## Usage

All commands accept `--profile`, `--region`, `--owner`, `--project`, and
`--environment` at the top level (before the resource name). `--owner`
defaults to your AWS identity (the IAM user/role behind your credentials),
so you usually don't need to pass it.

```bash
platform-cli --profile platform-cli-exam --region us-east-1 <resource> <action> [options]
```

### EC2

```bash
# Create an instance (t3.micro/t2.small only, latest AMI via SSM, capped at 2 running per owner)
platform-cli ec2 create --instance-type t3.micro --os-family ubuntu --name my-dev-box

# List instances this tool created for you
platform-cli ec2 list

# Start / stop (only works on instances this tool created for you)
platform-cli ec2 start --instance-id i-0123456789abcdef0
platform-cli ec2 stop  --instance-id i-0123456789abcdef0

# Terminate: permanent, requires explicit confirmation
platform-cli ec2 terminate --instance-id i-0123456789abcdef0
# -> Instance 'i-0123456789abcdef0' will be PERMANENTLY TERMINATED. Are you sure? [y/N]:
```

### S3

```bash
# Private bucket (default): encrypted, public access blocked
platform-cli s3 create --bucket-name my-globally-unique-bucket-name

# Public bucket: requires explicit confirmation
platform-cli s3 create --bucket-name my-public-bucket --public
# -> Bucket 'my-public-bucket' will be PUBLIC. Are you sure? [y/N]:

platform-cli s3 upload --bucket-name my-globally-unique-bucket-name --file ./report.csv

platform-cli s3 list

# Delete: permanent, requires explicit confirmation, bucket must be empty
platform-cli s3 delete --bucket-name my-globally-unique-bucket-name
```

### Route53

```bash
platform-cli route53 create-zone --zone-name example.test.

platform-cli route53 create-record --zone-id Z0123456789EXAMPLE \
    --name www.example.test. --type A --value 1.2.3.4

platform-cli route53 update-record --zone-id Z0123456789EXAMPLE \
    --name www.example.test. --type A --value 5.6.7.8

platform-cli route53 delete-record --zone-id Z0123456789EXAMPLE \
    --name www.example.test. --type A

platform-cli route53 list-zones
platform-cli route53 list-records --zone-id Z0123456789EXAMPLE
```

Run `platform-cli --help`, or `platform-cli <resource> --help`, or
`platform-cli <resource> <action> --help` for full option lists at any level.

## Tagging convention

Every resource this tool creates gets four tags:

| Tag          | Meaning                                              |
|--------------|-------------------------------------------------------|
| `CreatedBy`  | Always `platform-cli` — marks it as tool-managed      |
| `Owner`      | The AWS identity that created it (or `--owner` override) |
| `Project`    | Defaults to `platform-cli`, override with `--project` |
| `Environment`| Defaults to `dev`, override with `--environment`      |

`list`, `start`, `stop`, `terminate`, `upload`, and `delete` all filter by
**both** `CreatedBy` and `Owner` — not just `CreatedBy`. This matters on a
shared account: without the `Owner` check, one user's 2-instance cap could
be exhausted by someone else's instances, and `list` would show everyone's
resources instead of just yours.

## Cleanup

`ec2 terminate` and `s3 delete` both require typing `y` at an explicit
confirmation prompt — irreversible deletes deserve deliberate action, not a
single accidental flag.

```bash
platform-cli ec2 terminate --instance-id i-0123456789abcdef0

# S3 buckets must be empty before deleting
aws s3 rm s3://my-bucket --recursive --profile platform-cli-exam
platform-cli s3 delete --bucket-name my-bucket

# Route53 has no zone-delete command (only record create/update/delete, per
# spec) - delete records first (a zone can't be deleted while it holds
# non-default records), then remove the zone via the AWS CLI directly
platform-cli route53 delete-record --zone-id <id> --name <name> --type <type>
aws route53 delete-hosted-zone --id <id> --profile platform-cli-exam
```

You can always find what the tool created for you with `ec2 list`,
`s3 list`, and `route53 list-zones`.

## Web UI (optional)

A Streamlit UI (`app.py`) covers the same actions as the CLI through forms
instead of commands. It calls the exact same `platform_cli.ec2` / `.s3` /
`.route53` functions as `cli.py` — no logic is duplicated between the two.

```bash
pip install -r requirements-ui.txt
streamlit run app.py
```

This opens the UI at `http://localhost:8501`. Enter your AWS profile and
region in the sidebar, then use the EC2 / S3 / Route53 tabs. Public S3
buckets require checking an explicit confirmation checkbox before the
"Create bucket" button will do anything — the UI equivalent of the CLI's
`Are you sure? (yes/no)` prompt.
