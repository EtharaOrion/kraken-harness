def test_label_networkpolicy_0137_add_tier(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: lne-0137\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "networkpolicy", "lne-0137", "tier=backend", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "lne-0137" in result.stdout
