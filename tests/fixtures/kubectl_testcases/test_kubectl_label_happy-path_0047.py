def test_label_serviceaccount_0047_add_tier(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: lse-0047\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "serviceaccount", "lse-0047", "tier=backend", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0047" in result.stdout
