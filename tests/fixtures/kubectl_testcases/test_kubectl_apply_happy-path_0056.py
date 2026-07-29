def test_apply_networkpolicy_0056_dryrun_client(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: adne-0056\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=client")
    assert result.returncode == 0, result.stderr
    assert "adne-0056" in result.stdout
