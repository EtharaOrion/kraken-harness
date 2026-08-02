def test_describe_networkpolicy_0233_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: esne-0233\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "networkpolicy", "esne-0233", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esne-0233" in result.stdout
