def test_describe_networkpolicy_0019_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: ene-0019\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "networkpolicy", "ene-0019", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "ene-0019" in result.stdout
