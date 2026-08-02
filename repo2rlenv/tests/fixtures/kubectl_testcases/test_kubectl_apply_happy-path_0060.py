def test_apply_service_0060_dryrun_server(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: asse-0060\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    result = cli("apply", "-f", str(manifest), "--dry-run=server")
    assert result.returncode == 0, result.stderr
    assert "asse-0060" in result.stdout
