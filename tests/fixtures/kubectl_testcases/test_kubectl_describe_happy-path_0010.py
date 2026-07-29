def test_describe_serviceaccount_0010_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: ese-0010\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "serviceaccount", "ese-0010", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ese-0010" in result.stdout
