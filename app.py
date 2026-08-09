"""Streamlit UI for platform-cli - reuses the exact same ec2/s3/route53
functions as the CLI (platform_cli/cli.py). No business logic lives here,
only widgets and glue code."""

import tempfile
from pathlib import Path

import streamlit as st

from platform_cli import ec2, route53, s3
from platform_cli.aws import PlatformCliError, get_caller_username, get_session

st.set_page_config(page_title="platform-cli", layout="wide")


@st.cache_resource(show_spinner=False)
def _cached_session(profile: str, region: str):
    return get_session(profile=profile or None, region=region or None)


@st.cache_resource(show_spinner=False)
def _cached_owner(profile: str, region: str, override: str):
    if override:
        return override
    return get_caller_username(_cached_session(profile, region))


st.sidebar.header("Connection")
profile = st.sidebar.text_input("AWS profile", value="")
region = st.sidebar.text_input("AWS region", value="us-east-1")
owner_override = st.sidebar.text_input("Owner (optional override)", value="")
project = st.sidebar.text_input("Project", value="platform-cli")
environment = st.sidebar.text_input("Environment", value="dev")

try:
    session = _cached_session(profile, region)
    owner = _cached_owner(profile, region, owner_override)
except PlatformCliError as exc:
    st.sidebar.error(str(exc))
    st.stop()

st.sidebar.success(f"Connected as: {owner}")

st.title("platform-cli")
st.caption("Self-service AWS provisioning within guardrails - same engine as the CLI.")

ec2_tab, s3_tab, route53_tab = st.tabs(["EC2", "S3", "Route53"])

# ---------- EC2 ----------

with ec2_tab:
    st.subheader("Create instance")
    with st.form("ec2_create"):
        instance_type = st.selectbox("Instance type", sorted(ec2.ALLOWED_INSTANCE_TYPES))
        os_family = st.selectbox("OS family", sorted(ec2.AMI_SSM_PARAMS))
        name = st.text_input("Name (optional)")
        if st.form_submit_button("Create instance"):
            try:
                result = ec2.create_instance(
                    session,
                    owner=owner,
                    project=project,
                    environment=environment,
                    instance_type=instance_type,
                    os_family=os_family,
                    name=name or None,
                )
                st.success(f"Created {result['InstanceId']} (state={result['State']})")
            except PlatformCliError as exc:
                st.error(str(exc))

    st.subheader("Your instances")
    if st.button("Refresh instance list"):
        st.session_state["ec2_instances"] = ec2.list_instances(session, owner)
    instances = st.session_state.get("ec2_instances", [])
    if instances:
        st.dataframe(instances, use_container_width=True)

        instance_id = st.selectbox("Instance to start/stop/terminate", [i["InstanceId"] for i in instances])
        col1, col2, col3 = st.columns(3)
        if col1.button("Start"):
            try:
                ec2.start_instance(session, instance_id, owner)
                st.success(f"Started {instance_id}")
            except PlatformCliError as exc:
                st.error(str(exc))
        if col2.button("Stop"):
            try:
                ec2.stop_instance(session, instance_id, owner)
                st.success(f"Stopped {instance_id}")
            except PlatformCliError as exc:
                st.error(str(exc))

        terminate_confirmed = st.checkbox(f"Confirm - permanently terminate {instance_id}")
        if col3.button("Terminate", disabled=not terminate_confirmed):
            try:
                ec2.terminate_instance(session, instance_id, owner, confirmed=terminate_confirmed)
                st.success(f"Terminated {instance_id}")
            except PlatformCliError as exc:
                st.error(str(exc))
    else:
        st.info("No instances loaded yet - click 'Refresh instance list'.")

# ---------- S3 ----------

with s3_tab:
    st.subheader("Create bucket")
    with st.form("s3_create"):
        bucket_name = st.text_input("Bucket name (globally unique)")
        public = st.checkbox("Make this bucket public")
        confirmed = st.checkbox("Confirm - this bucket will be publicly readable", disabled=not public)
        if st.form_submit_button("Create bucket"):
            if public and not confirmed:
                st.error("Check the confirmation box to create a public bucket.")
            else:
                try:
                    result = s3.create_bucket(
                        session,
                        bucket_name,
                        owner=owner,
                        project=project,
                        environment=environment,
                        public=public,
                        confirmed=confirmed,
                    )
                    st.success(f"Created bucket {result['BucketName']} (public={result['Public']})")
                except PlatformCliError as exc:
                    st.error(str(exc))

    st.subheader("Your buckets")
    if st.button("Refresh bucket list"):
        st.session_state["s3_buckets"] = s3.list_buckets(session, owner)
    buckets = st.session_state.get("s3_buckets", [])
    if buckets:
        st.dataframe(buckets, use_container_width=True)

        st.subheader("Upload a file")
        bucket_choice = st.selectbox("Target bucket", [b["BucketName"] for b in buckets])
        uploaded = st.file_uploader("Choose a file")
        if uploaded and st.button("Upload"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            try:
                result = s3.upload_file(session, bucket_choice, tmp_path, owner=owner, key=uploaded.name)
                st.success(f"Uploaded to s3://{result['BucketName']}/{result['Key']}")
            except PlatformCliError as exc:
                st.error(str(exc))
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        st.subheader("Delete a bucket")
        delete_choice = st.selectbox("Bucket to delete", [b["BucketName"] for b in buckets], key="delete_bucket")
        delete_confirmed = st.checkbox(f"Confirm - permanently delete {delete_choice} (must be empty)")
        if st.button("Delete bucket", disabled=not delete_confirmed):
            try:
                s3.delete_bucket(session, delete_choice, owner, confirmed=delete_confirmed)
                st.success(f"Deleted bucket {delete_choice}")
            except PlatformCliError as exc:
                st.error(str(exc))
    else:
        st.info("No buckets loaded yet - click 'Refresh bucket list'.")

# ---------- Route53 ----------

with route53_tab:
    st.subheader("Create zone")
    with st.form("route53_create_zone"):
        zone_name = st.text_input("Zone name (e.g. example.com.)")
        if st.form_submit_button("Create zone"):
            try:
                result = route53.create_zone(session, zone_name, owner=owner, project=project, environment=environment)
                st.success(f"Created zone {result['ZoneId']} ({result['Name']})")
            except PlatformCliError as exc:
                st.error(str(exc))

    st.subheader("Your zones")
    if st.button("Refresh zone list"):
        st.session_state["route53_zones"] = route53.list_zones(session, owner)
    zones = st.session_state.get("route53_zones", [])
    if zones:
        st.dataframe(zones, use_container_width=True)

        zone_id = st.selectbox("Zone", [z["ZoneId"] for z in zones])

        st.subheader("Records")
        if st.button("Refresh record list"):
            st.session_state["route53_records"] = route53.list_records(session, zone_id, owner)
        records = st.session_state.get("route53_records", [])
        if records:
            st.dataframe(records, use_container_width=True)

        with st.form("route53_record"):
            record_name = st.text_input("Record name")
            record_type = st.text_input("Record type (A, CNAME, TXT, ...)", value="A")
            values_raw = st.text_input("Value(s), comma-separated")
            ttl = st.number_input("TTL", value=300, min_value=1)
            col1, col2, col3 = st.columns(3)
            create_clicked = col1.form_submit_button("Create")
            update_clicked = col2.form_submit_button("Update")
            delete_clicked = col3.form_submit_button("Delete")

        values = [v.strip() for v in values_raw.split(",") if v.strip()]
        try:
            if create_clicked:
                route53.create_record(session, zone_id, owner, record_name, record_type, values, ttl)
                st.success(f"Created {record_name} ({record_type})")
            elif update_clicked:
                route53.update_record(session, zone_id, owner, record_name, record_type, values, ttl)
                st.success(f"Updated {record_name} ({record_type})")
            elif delete_clicked:
                route53.delete_record(session, zone_id, owner, record_name, record_type)
                st.success(f"Deleted {record_name} ({record_type})")
        except PlatformCliError as exc:
            st.error(str(exc))
    else:
        st.info("No zones loaded yet - click 'Refresh zone list'.")
