"""cli_app DynamoDB backend + botocore-model extraction.

Locks in the DynamoDB enablement of the cli_app pipeline and, crucially, that
the S3/MinIO path stays byte-identical (task_id/content_hash inputs, conftest,
prompt-template version, pinned deps, blocklist). No Docker, no LLM — exercises
the deterministic builders + the shipped stdlib helper via ``exec``. ~1s.
"""

from __future__ import annotations

import ast

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.emitter import harbor
from repo2rlenv.pipelines._cli_app_extract import (
    CliSpec,
    CommandSpec,
    _member_to_flag,
    _op_to_cli_name,
    synthesize_intents_from_model,
)
from repo2rlenv.spec.options import CodeInstructOptions

_VERBS = [
    "create-table",
    "delete-table",
    "list-tables",
    "put-item",
    "get-item",
    "update-item",
    "delete-item",
    "query",
]
_OPS = {
    "create-table": "CreateTable",
    "delete-table": "DeleteTable",
    "list-tables": "ListTables",
    "put-item": "PutItem",
    "get-item": "GetItem",
    "update-item": "UpdateItem",
    "delete-item": "DeleteItem",
    "query": "Query",
}


def _mini_model() -> dict:
    model: dict = {
        "operations": {},
        "shapes": {
            "S": {"type": "string"},
            "M": {"type": "map", "value": {"shape": "S"}},
            "L": {"type": "list", "member": {"shape": "S"}},
        },
    }
    for op in _OPS.values():
        shape = op + "Input"
        model["operations"][op] = {
            "documentation": f"<p>{op} does a thing.</p>",
            "input": {"shape": shape},
            "errors": [{"shape": "ResourceNotFoundException"}, {"shape": "ValidationException"}],
        }
        model["shapes"][shape] = {
            "type": "structure",
            "required": ["TableName"],
            "members": {
                "TableName": {"shape": "S"},
                "Key": {"shape": "M"},
                "Item": {"shape": "M"},
            },
        }
    return model


def _ddb_spec() -> CliSpec:
    return CliSpec(
        name="aws_cli_dynamodb",
        command_prefix="dynamodb",
        repo="aws/aws-cli",
        git_sha="ab" * 20,
        entry_point="botocore/data/dynamodb/2012-08-10/service-2.json",
        tests_dir="",
        commands=[CommandSpec(name=v) for v in _VERBS],
    )


# ---------------------------------------------------------------------------
# Extraction (botocore service model)
# ---------------------------------------------------------------------------


def test_op_and_member_casing() -> None:
    assert _op_to_cli_name("CreateTable") == "create-table"
    assert _op_to_cli_name("ListTables") == "list-tables"
    assert _op_to_cli_name("Query") == "query"
    assert _member_to_flag("TableName") == "--table-name"
    assert _member_to_flag("KeySchema") == "--key-schema"
    assert _member_to_flag("SSESpecification") == "--sse-specification"


def test_extract_cli_spec_from_model_reads_disk(tmp_path) -> None:
    import json

    from repo2rlenv.pipelines._cli_app_extract import (
        extract_cli_spec_from_model,
        find_service_model_json,
    )

    model_dir = tmp_path / "clone" / "awscli" / "botocore" / "data" / "dynamodb" / "2012-08-10"
    model_dir.mkdir(parents=True)
    (model_dir / "service-2.json").write_text(json.dumps(_mini_model()))
    clone = tmp_path / "clone"

    found = find_service_model_json(clone, "dynamodb")
    assert found.name == "service-2.json"

    spec, model = extract_cli_spec_from_model(
        clone,
        "dynamodb",
        repo="aws/aws-cli",
        git_sha="deadbeef",
        target_operations=("CreateTable", "PutItem", "GetItem"),
    )
    assert spec.name == "aws_cli_dynamodb"
    assert {c.name for c in spec.commands} == {"create-table", "put-item", "get-item"}
    assert spec.spec_sha256  # canonical hash computed
    # botocore data is never imported — the model came back as a plain dict.
    assert isinstance(model, dict) and "operations" in model


def test_synthesize_intents_diversity() -> None:
    model = _mini_model()
    intents = synthesize_intents_from_model(model, "put-item", "dynamodb", max_intents=100)
    tags = {i.behaviour_tag for i in intents}
    assert "happy_path" in tags
    assert "error_invalid_args" in tags or "error_nonexistent" in tags
    happy = [i for i in intents if i.behaviour_tag == "happy_path"]
    assert len(happy) >= 2
    assert happy[0].cmdline_template[:2] == ["dynamodb", "put-item"]
    assert "def test_" not in happy[0].raw_source
    assert "Operation: PutItem" in happy[0].raw_source


# ---------------------------------------------------------------------------
# Shipped stdlib DynamoDB client (_ddb_http.py)
# ---------------------------------------------------------------------------


_FORBIDDEN_USAGE = (
    "import boto3",
    "import botocore",
    "from boto3",
    "from botocore",
    "from moto",
    "import moto",
    "boto3.client",
    "ThreadedMotoServer",
)


def test_ddb_http_helper_marshals_and_is_no_boto() -> None:
    helper = S._DDB_HTTP_HELPER
    for token in _FORBIDDEN_USAGE:
        assert token not in helper, f"{token} leaked into _ddb_http.py"
    ns: dict = {}
    exec(compile(helper, "_ddb_http", "exec"), ns)  # trusted generated string
    to_av, from_av = ns["to_av"], ns["from_av"]
    to_item, from_item = ns["to_item"], ns["from_item"]
    assert to_av(5) == {"N": "5"}  # numbers are JSON strings
    assert to_av(5.0) == {"N": "5"}
    assert to_av(2.5) == {"N": "2.5"}
    assert to_av(True) == {"BOOL": True}
    assert to_av(None) == {"NULL": True}
    assert to_av({"a": 1}) == {"M": {"a": {"N": "1"}}}
    assert from_av({"N": "7"}) == 7
    assert from_item(to_item({"pk": "abc", "n": 5})) == {"pk": "abc", "n": 5}
    err = ns["DDBHTTPError"]("ResourceNotFoundException", "msg", 400, "GetItem")
    assert err.response["Error"]["Code"] == "ResourceNotFoundException"


def test_ddb_conftest_valid_no_boto_dynamodb_local() -> None:
    conftest = S._build_conftest(backend="dynamodb_local")
    ast.parse(conftest)
    assert "DynamoDBLocal.jar" not in conftest
    assert "subprocess.Popen" not in conftest
    assert "http://ddb:8000" in conftest
    assert "AWS_ENDPOINT_URL_DYNAMODB" in conftest
    assert "reset_all_tables" in conftest
    assert "from _ddb_http import" in conftest
    for token in (*_FORBIDDEN_USAGE, "minio", "Minio"):
        assert token not in conftest, f"{token} leaked into DynamoDB conftest"


def test_ddb_dockerfile_is_sidecar_shaped() -> None:
    out = S._build_dockerfile(backend="dynamodb_local")
    assert S.PINNED_DDB_BASE_IMAGE in out
    assert "aws_cli_dynamodb" in out
    assert "minio" not in out
    assert "MINIO_" not in out
    assert "amazon/dynamodb-local" not in out
    assert "COPY --from=ddblocal" not in out
    assert "openjdk-17-jre-headless" not in out
    assert "JAVA_TOOL_OPTIONS" not in out
    assert "AWS_ENDPOINT_URL=http://ddb:8000" in out
    assert "AWS_ACCESS_KEY_ID=raidentest" in out
    for token in _FORBIDDEN_USAGE:
        assert token not in out


def test_ddb_compose_emits_sidecar() -> None:
    compose = harbor._build_disallow_compose(harbor.BLOCKED_HOSTS_DDB, ddb_sidecar=True)
    assert "services:" in compose
    assert "  ddb:" in compose
    assert "amazon/dynamodb-local:2.5.4" in compose
    assert "healthcheck:" in compose
    assert "condition: service_healthy" in compose
    assert "AWS_ENDPOINT_URL=http://ddb:8000" in compose
    assert "AWS_ENDPOINT_URL_DYNAMODB=http://ddb:8000" in compose
    assert "extra_hosts:" in compose
    assert "pypi.org" in compose


def test_disallow_compose_default_unchanged() -> None:
    assert harbor._build_disallow_compose(harbor.BLOCKED_HOSTS) == harbor.NETWORK_DISALLOW_COMPOSE


# ---------------------------------------------------------------------------
# Instruction builders (leakage-clean for every verb + subset)
# ---------------------------------------------------------------------------


def test_ddb_instructions_leakage_clean() -> None:
    spec = _ddb_spec()
    model = _mini_model()

    def intents(cmd: str) -> list:
        return synthesize_intents_from_model(model, cmd, "dynamodb", max_intents=8)

    for cmd in spec.commands:
        md = S._build_instruction_md(spec, cmd, intents(cmd.name), backend="dynamodb_local")
        S._assert_no_test_leakage(md, {})  # raises on any leak
        assert "DynamoDB" in md
        assert "ab" * 20 not in md  # git sha must not leak

    subset = [c for c in spec.commands if c.name in ("put-item", "get-item", "query")]
    sub_intents: list = []
    for c in subset:
        sub_intents.extend(intents(c.name))
    md = S._build_subset_instruction_md(spec, subset, sub_intents, backend="dynamodb_local")
    S._assert_no_test_leakage(md, {})


# ---------------------------------------------------------------------------
# Prompt selection + backend-scoped prompt-template version
# ---------------------------------------------------------------------------


def test_prompt_template_version_is_backend_scoped() -> None:
    minio_opts = CodeInstructOptions(mode="cli_app", cli_app_command_prefix="s3")
    ddb_opts = CodeInstructOptions(
        mode="cli_app", cli_app_command_prefix="dynamodb", cli_app_backend="dynamodb_local"
    )
    assert S._prompt_template_version(minio_opts) == S.PROMPT_TEMPLATE_VERSION
    assert S._prompt_template_version(ddb_opts) == S.PROMPT_TEMPLATE_VERSION_DDB
    assert S.PROMPT_TEMPLATE_VERSION != S.PROMPT_TEMPLATE_VERSION_DDB


def test_ddb_prompts_forbid_boto_and_teach_wire_protocol() -> None:
    for name in (
        "TRANSLATION_SYSTEM_DDB",
        "ORACLE_SYSTEM_DDB",
        "ORACLE_SUBSET_SYSTEM_DDB",
        "WORKFLOW_SYSTEM_DDB",
    ):
        prompt = getattr(S, name)
        # The prompt must NAME boto3/botocore/moto as forbidden (parity with S3).
        for token in ("boto3", "botocore", "moto"):
            assert token in prompt, f"{name} forbidden block must mention {token}"
    # Oracle prompts teach the raw wire protocol; translation/workflow use ddb_client.
    assert "X-Amz-Target" in S.ORACLE_SYSTEM_DDB
    assert "DynamoDB_20120810" in S.ORACLE_SYSTEM_DDB
    assert "ddb_client" in S.TRANSLATION_SYSTEM_DDB
    assert "ddb_client" in S.WORKFLOW_SYSTEM_DDB


# ---------------------------------------------------------------------------
# S3 / MinIO regression safety
# ---------------------------------------------------------------------------


def test_minio_conftest_byte_identical_across_default_and_explicit() -> None:
    assert S._build_conftest() == S._build_conftest(backend="minio")
    # DynamoDB divergence is a separate string, not a mutation of the MinIO one.
    assert S._build_conftest(backend="minio") != S._build_conftest(backend="dynamodb_local")


def test_minio_pipeline_constants_unchanged() -> None:
    assert "minio==" in " ".join(S.PINNED_DEPS)
    assert S.PROMPT_TEMPLATE_VERSION == "v2.0.0-minio"
    assert S.PINNED_DEPS_DDB == ("pytest==8.3.3",)


def test_blocklist_ddb_is_additive_and_aligned() -> None:
    # Base S3 tuples are untouched (S3 conftest bakes BLOCKED_SUFFIXES).
    assert set(harbor.BLOCKED_SUFFIXES) <= set(harbor.BLOCKED_SUFFIXES_DDB)
    assert set(harbor.BLOCKED_HOSTS) <= set(harbor.BLOCKED_HOSTS_DDB)
    assert "dynamodb.amazonaws.com" in harbor.BLOCKED_SUFFIXES_DDB
    assert "dynamodb.amazonaws.com" not in harbor.BLOCKED_SUFFIXES
    # Alignment invariant holds for the DDB set (would raise on import otherwise).
    harbor._verify_blocklist_alignment(harbor.BLOCKED_HOSTS_DDB, harbor.BLOCKED_SUFFIXES_DDB)


def test_cli_app_oracle_defaults_to_both_with_llm_optout() -> None:
    o = CodeInstructOptions(
        mode="cli_app", cli_app_command_prefix="dynamodb", cli_app_backend="dynamodb_local"
    )
    assert o.cli_app_oracle == "both"
    o_llm = CodeInstructOptions(
        mode="cli_app",
        cli_app_command_prefix="dynamodb",
        cli_app_backend="dynamodb_local",
        cli_app_oracle="llm",
    )
    assert o_llm.cli_app_oracle == "llm"
