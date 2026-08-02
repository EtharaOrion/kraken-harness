def test_apply_limitrange_0066_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: asli-0066\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asli-0066" in result.stdout
