# Demo Evidence

All commands below were run for real against a live AWS account (a shared
classroom account), using `platform-cli` after `pip install -e .`. Output is
pasted verbatim, unedited except for removing timestamps of no interest.

Environment: `--profile platform-cli-exam --region us-east-1`, resolved
owner: `stav` (from AWS identity, not a flag).

## EC2 — create / list / start / stop

```
$ platform-cli ec2 create --instance-type t3.micro --os-family ubuntu --name demo-instance
Created instance i-046d67f429fbbff90 (state=pending, type=t3.micro)

$ platform-cli ec2 list
i-0a4cee7151021801b  stopped     t3.micro    exam-test-instance    owner=stav
i-06928f3505ddad9f1  stopped     t3.micro    exam-test-instance-2  owner=stav
i-0273e97dee661a9c6  stopped     t3.micro    exam-test-instance-3  owner=stav
i-046d67f429fbbff90  running     t3.micro    demo-instance         owner=stav

$ platform-cli ec2 stop --instance-id i-046d67f429fbbff90
Stopped instance i-046d67f429fbbff90

$ platform-cli ec2 list
i-0a4cee7151021801b  stopped     t3.micro    exam-test-instance    owner=stav
i-06928f3505ddad9f1  stopped     t3.micro    exam-test-instance-2  owner=stav
i-0273e97dee661a9c6  stopped     t3.micro    exam-test-instance-3  owner=stav
i-046d67f429fbbff90  stopped     t3.micro    demo-instance         owner=stav

$ platform-cli ec2 start --instance-id i-046d67f429fbbff90
Started instance i-046d67f429fbbff90

$ platform-cli ec2 list
i-0a4cee7151021801b  stopped     t3.micro    exam-test-instance    owner=stav
i-06928f3505ddad9f1  stopped     t3.micro    exam-test-instance-2  owner=stav
i-0273e97dee661a9c6  stopped     t3.micro    exam-test-instance-3  owner=stav
i-046d67f429fbbff90  running     t3.micro    demo-instance         owner=stav
```

(The three `exam-test-instance*` entries are earlier, real test instances
created by this same tool during development — left in place on purpose, see
[README - Cleanup](README.md#cleanup). `demo-instance` was stopped again
right after this capture to avoid leaving it running.)

### Guardrail: instance type validated before touching AWS

```
$ platform-cli ec2 create --instance-type m5.large
Usage: platform-cli ec2 create [OPTIONS]
Try 'platform-cli ec2 create --help' for help.

Error: Invalid value for '--instance-type': 'm5.large' is not one of 't2.small', 't3.micro'.
```

### Guardrail: can't touch another user's instance

This account is shared with classmates; `i-04849ce74bce6173d` belongs to
another student's run of the same tool:

```
$ platform-cli ec2 stop --instance-id i-04849ce74bce6173d
Error: Instance 'i-04849ce74bce6173d' was not created by this tool for owner 'stav'.
```

### Guardrail: 2-running-instance cap (including the pending-state race)

Captured during module testing (`platform_cli.ec2.create_instance` calls),
same logic the CLI calls into:

```
>>> create_instance(session, owner=owner, name='exam-test-instance-2')
created 2nd: {'InstanceId': 'i-06928f3505ddad9f1', ...}
>>> create_instance(session, owner=owner, name='exam-test-instance-3')
Correctly blocked: Cannot create instance: 2 CLI-created instances are already running (limit is 2).
```

## S3 — create (private + public) / upload / list

```
$ platform-cli s3 create --bucket-name platform-cli-exam-stav-992382545251-demo
Created bucket platform-cli-exam-stav-992382545251-demo (public=False, region=us-east-1)

$ platform-cli s3 upload --bucket-name platform-cli-exam-stav-992382545251-demo --file test-upload.txt
Uploaded to s3://platform-cli-exam-stav-992382545251-demo/test-upload.txt

$ platform-cli s3 list
platform-cli-exam-stav-992382545251-demo     created=2026-08-08T14:10:43+00:00  owner=stav
platform-cli-exam-stav-992382545251-private  created=2026-08-08T13:39:30+00:00  owner=stav
```

### Public bucket requires explicit confirmation

```
$ echo yes | platform-cli s3 create --bucket-name platform-cli-exam-stav-992382545251-demo-public --public
Bucket 'platform-cli-exam-stav-992382545251-demo-public' will be PUBLIC. Are you sure? [y/N]: Created bucket platform-cli-exam-stav-992382545251-demo-public (public=True, region=us-east-1)
```

(Answer piped via `echo yes |` for a non-interactive capture, so the typed
answer itself doesn't appear in the output above - only the prompt and the
result. Run interactively, you'd type `yes` right after the `[y/N]:` prompt.)

Verified the bucket really is publicly readable, with no AWS credentials
involved - a plain unauthenticated HTTPS request:

```
$ curl -s -o - -w "\nHTTP_STATUS:%{http_code}\n" \
    "https://platform-cli-exam-stav-992382545251-demo-public.s3.amazonaws.com/test-upload.txt"
hello from platform-cli s3 module test

HTTP_STATUS:200
```

(This test bucket was deleted right after capturing the above - a public
bucket has no reason to keep existing once its behavior is confirmed.)

Declining the confirmation aborts cleanly, no bucket is created:

```
$ echo no | platform-cli s3 create --bucket-name some-other-bucket --public
Bucket 'some-other-bucket' will be PUBLIC. Are you sure? [y/N]: Aborted.
```

## Route53 — zone + record create / update / delete / list

```
$ platform-cli route53 create-zone --zone-name demo.stav-platform-cli-exam.test.
Created zone Z01005591NOWIFWOS92BA (demo.stav-platform-cli-exam.test.)
  NS: ns-406.awsdns-50.com
  NS: ns-1228.awsdns-25.org
  NS: ns-1013.awsdns-62.net
  NS: ns-1584.awsdns-06.co.uk

$ platform-cli route53 list-zones
Z0108436IXZEJBB3AIL9      stav-platform-cli-exam.test.              owner=stav
Z01005591NOWIFWOS92BA     demo.stav-platform-cli-exam.test.         owner=stav

$ platform-cli route53 create-record --zone-id Z01005591NOWIFWOS92BA \
    --name www.demo.stav-platform-cli-exam.test. --type A --value 1.2.3.4
Created record www.demo.stav-platform-cli-exam.test. (A)

$ platform-cli route53 list-records --zone-id Z01005591NOWIFWOS92BA
demo.stav-platform-cli-exam.test.         NS      ttl=172800  ns-406.awsdns-50.com., ns-1228.awsdns-25.org., ns-1013.awsdns-62.net., ns-1584.awsdns-06.co.uk.
demo.stav-platform-cli-exam.test.         SOA     ttl=900  ns-406.awsdns-50.com. awsdns-hostmaster.amazon.com. 1 7200 900 1209600 86400
www.demo.stav-platform-cli-exam.test.     A       ttl=300  1.2.3.4

$ platform-cli route53 update-record --zone-id Z01005591NOWIFWOS92BA \
    --name www.demo.stav-platform-cli-exam.test. --type A --value 5.6.7.8
Updated record www.demo.stav-platform-cli-exam.test. (A)

$ platform-cli route53 delete-record --zone-id Z01005591NOWIFWOS92BA \
    --name www.demo.stav-platform-cli-exam.test. --type A
Deleted record www.demo.stav-platform-cli-exam.test. (A)
```

## Bugs found and fixed during this development (kept here as evidence of real, non-mocked testing)

Both were only caught because the code was run against real AWS instead of
assumed correct:

1. **EC2 cap race condition** - the running-instance count only checked
   `instance-state-name=running`, but a just-launched instance sits in
   `pending` for a few seconds first. Creating instances back-to-back could
   slip a 3rd one past the 2-instance cap during that window. Fixed by
   counting `pending` and `running` together.
2. **EC2 cap not enforced on start** - the cap was only checked in
   `create_instance`, so `create → stop → create → start` could still end
   up with 3 running instances. Fixed by adding the same cap check to
   `start_instance`.
3. **S3 list crashed on an inaccessible bucket** - a course-admin bucket
   (`nitzanimadminbucket`) has an explicit IAM deny against student users
   for `GetBucketTagging`, which raised `AccessDenied` and crashed the
   whole `list_buckets` loop instead of just skipping that one bucket.
