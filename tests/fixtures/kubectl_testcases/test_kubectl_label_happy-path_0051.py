def test_label_serviceaccount_0051_add_region(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: lse-0051\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "serviceaccount", "lse-0051", "region=eu-central", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lse-0051" in result.stdout
