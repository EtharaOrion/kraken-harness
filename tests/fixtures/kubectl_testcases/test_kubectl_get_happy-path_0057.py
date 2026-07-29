def test_get_serviceaccount_0057_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: gfse-0057\n  namespace: default\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "serviceaccount", "gfse-0057", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
