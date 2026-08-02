def test_patch_resourcequota_0025_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: pre-0025\n  namespace: default\nspec:\n  hard:\n    pods: "10"\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "resourcequota", "pre-0025", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b25"}}}')
    assert result.returncode == 0, result.stderr
    assert "pre-0025" in result.stdout
