from __future__ import annotations

import json

import pytest

from repo2rlenv.pipelines._cli_app_slice import (
    _GENERATED_HANDLERS_DDB,
    _GENERATED_HANDLERS_S3,
    SliceError,
    _assert_ddb_slice_closed,
    _service_data_dirs,
    _service_endpoints_keep,
    _service_handlers_src,
    _slice_dynamodb_data,
    _verb_to_operation,
)


def _write_fake_ddb(tmp_path, service_model):
    ddb_dir = tmp_path / "awscli" / "botocore" / "data" / "dynamodb" / "2012-08-10"
    ddb_dir.mkdir(parents=True)
    (ddb_dir / "service-2.json").write_text(json.dumps(service_model), encoding="utf-8")
    return tmp_path / "awscli"


def test_verb_to_operation_conversion():
    assert _verb_to_operation("put-item") == "PutItem"
    assert _verb_to_operation("batch-get-item") == "BatchGetItem"
    assert _verb_to_operation("list-tables") == "ListTables"


def test_slice_prunes_to_requested_op_with_full_shape_closure(tmp_path):
    service_model = {
        "version": "2.0",
        "metadata": {"apiVersion": "2012-08-10", "protocol": "json"},
        "operations": {
            "PutItem": {
                "name": "PutItem",
                "input": {"shape": "PutItemInput"},
                "output": {"shape": "PutItemOutput"},
                "errors": [{"shape": "ResourceNotFoundException"}],
            },
            "GetItem": {
                "name": "GetItem",
                "input": {"shape": "GetItemInput"},
                "output": {"shape": "GetItemOutput"},
                "errors": [{"shape": "ResourceNotFoundException"}],
            },
            "ListTables": {
                "name": "ListTables",
                "input": {"shape": "ListTablesInput"},
                "output": {"shape": "ListTablesOutput"},
                "errors": [],
            },
        },
        "shapes": {
            "PutItemInput": {
                "type": "structure",
                "members": {
                    "TableName": {"shape": "TableName"},
                    "Item": {"shape": "AttributeMap"},
                },
            },
            "PutItemOutput": {
                "type": "structure",
                "members": {"Attributes": {"shape": "AttributeMap"}},
            },
            "GetItemInput": {
                "type": "structure",
                "members": {
                    "TableName": {"shape": "TableName"},
                    "Key": {"shape": "AttributeMap"},
                },
            },
            "GetItemOutput": {
                "type": "structure",
                "members": {"Item": {"shape": "AttributeMap"}},
            },
            "ListTablesInput": {"type": "structure", "members": {}},
            "ListTablesOutput": {
                "type": "structure",
                "members": {"TableNames": {"shape": "TableNameList"}},
            },
            "TableName": {"type": "string"},
            "TableNameList": {"type": "list", "member": {"shape": "TableName"}},
            "AttributeMap": {
                "type": "map",
                "key": {"shape": "AttributeName"},
                "value": {"shape": "AttributeValue"},
            },
            "AttributeName": {"type": "string"},
            "AttributeValue": {
                "type": "structure",
                "members": {"S": {"shape": "StringAttributeValue"}},
            },
            "StringAttributeValue": {"type": "string"},
            "ResourceNotFoundException": {
                "type": "structure",
                "members": {"message": {"shape": "ErrorMessage"}},
            },
            "ErrorMessage": {"type": "string"},
        },
    }
    awscli_root = _write_fake_ddb(tmp_path, service_model)

    overrides = _slice_dynamodb_data(awscli_root, ["put-item"])

    service_path = awscli_root / "botocore" / "data" / "dynamodb" / "2012-08-10" / "service-2.json"
    assert service_path in overrides
    pruned = json.loads(overrides[service_path])

    assert set(pruned["operations"]) == {"PutItem"}
    assert set(pruned["shapes"]) == {
        "PutItemInput",
        "PutItemOutput",
        "TableName",
        "AttributeMap",
        "AttributeName",
        "AttributeValue",
        "StringAttributeValue",
        "ResourceNotFoundException",
        "ErrorMessage",
    }


def test_slice_unknown_verb_raises(tmp_path):
    service_model = {
        "version": "2.0",
        "metadata": {"apiVersion": "2012-08-10"},
        "operations": {
            "PutItem": {
                "name": "PutItem",
                "input": {"shape": "PutItemInput"},
                "output": {"shape": "PutItemOutput"},
                "errors": [],
            },
        },
        "shapes": {
            "PutItemInput": {"type": "structure", "members": {}},
            "PutItemOutput": {"type": "structure", "members": {}},
        },
    }
    awscli_root = _write_fake_ddb(tmp_path, service_model)

    with pytest.raises(SliceError, match="unknown ops"):
        _slice_dynamodb_data(awscli_root, ["not-a-real-verb"])


def test_assert_ddb_slice_closed_detects_missing_shape():
    operations = {
        "PutItem": {
            "input": {"shape": "PutItemInput"},
            "output": {"shape": "PutItemOutput"},
            "errors": [],
        },
    }
    shapes = {
        "PutItemInput": {
            "type": "structure",
            "members": {"Item": {"shape": "MissingShape"}},
        },
        "PutItemOutput": {"type": "structure", "members": {}},
    }
    with pytest.raises(SliceError, match="closure incomplete"):
        _assert_ddb_slice_closed(operations, shapes)


def test_service_config_curated_and_derived_generic() -> None:
    assert _service_data_dirs("dynamodb") == ("dynamodb",)
    assert _service_data_dirs("s3") == ("s3", "sts")
    assert _service_endpoints_keep("dynamodb") == frozenset({"dynamodb"})
    assert _service_handlers_src("s3") == _GENERATED_HANDLERS_S3

    assert _service_data_dirs("secretsmanager") == ("secretsmanager", "sts")
    assert _service_endpoints_keep("ssm") == frozenset({"ssm", "sts"})
    assert _service_handlers_src("dynamodb") == _GENERATED_HANDLERS_DDB
    assert _service_handlers_src("secretsmanager") == _GENERATED_HANDLERS_DDB
