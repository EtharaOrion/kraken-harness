def test_patch_serviceaccount_0018_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: pse-0018\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "serviceaccount", "pse-0018", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a18"}}}')
    assert result.returncode == 0, result.stderr
    assert "pse-0018" in result.stdout
