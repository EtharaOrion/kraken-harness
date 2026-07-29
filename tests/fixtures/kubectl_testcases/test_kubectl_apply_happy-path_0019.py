def test_apply_networkpolicy_0019_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: ane-0019\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ane-0019" in result.stdout
