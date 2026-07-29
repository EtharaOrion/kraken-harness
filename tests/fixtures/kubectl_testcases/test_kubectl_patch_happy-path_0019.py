def test_patch_serviceaccount_0019_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: pse-0019\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "serviceaccount", "pse-0019", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b19"}}}')
    assert result.returncode == 0, result.stderr
    assert "pse-0019" in result.stdout
