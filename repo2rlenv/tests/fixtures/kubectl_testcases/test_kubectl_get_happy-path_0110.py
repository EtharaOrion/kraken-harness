def test_get_networkpolicy_0110_output_jsonpa(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: gfne-0110\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "networkpolicy", "gfne-0110", "-n", "default", "-o", "jsonpath={.metadata.name}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
