def test_apply_networkpolicy_0088_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: aone-0088\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aone-0088" in result.stdout
