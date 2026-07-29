def test_patch_networkpolicy_0046_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: pne-0046\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "networkpolicy", "pne-0046", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b46"}}}')
    assert result.returncode == 0, result.stderr
    assert "pne-0046" in result.stdout
