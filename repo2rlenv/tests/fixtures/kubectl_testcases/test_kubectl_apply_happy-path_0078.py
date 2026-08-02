def test_apply_secret_0078_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Secret\nmetadata:\n  name: aose-0078\n  namespace: default\ntype: Opaque\nstringData:\n  token: s3cret\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aose-0078" in result.stdout
