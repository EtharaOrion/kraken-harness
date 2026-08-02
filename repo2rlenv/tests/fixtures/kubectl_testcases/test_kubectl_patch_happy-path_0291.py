def test_patch_networkpolicy_0291_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: pine-0291\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "networkpolicy", "pine-0291", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x291"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "networkpolicy", "pine-0291", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x291"}}}')
    assert r2.returncode == 0, r2.stderr
