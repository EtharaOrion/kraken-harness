def test_apply_service_0465_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: azse-0465\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azse-0465" in result.stdout
