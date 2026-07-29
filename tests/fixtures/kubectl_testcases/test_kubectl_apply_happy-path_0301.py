def test_apply_networkpolicy_0301_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: azne-0301\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azne-0301" in result.stdout
