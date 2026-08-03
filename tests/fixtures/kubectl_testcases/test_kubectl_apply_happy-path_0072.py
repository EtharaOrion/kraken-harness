def test_apply_networkpolicy_0072_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: asne-0072\n  namespace: default\nspec:\n  podSelector: {}\n  policyTypes: [Ingress]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asne-0072" in result.stdout
