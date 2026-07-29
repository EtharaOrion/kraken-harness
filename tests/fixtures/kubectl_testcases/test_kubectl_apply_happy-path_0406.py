def test_apply_resourcequota_0406_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: azre-0406\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azre-0406" in result.stdout
