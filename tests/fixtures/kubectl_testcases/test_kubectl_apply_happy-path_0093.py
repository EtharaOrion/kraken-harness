def test_apply_service_0093_view_last_applied(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: alse-0093\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "service", "alse-0093", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "alse-0093" in result.stdout
