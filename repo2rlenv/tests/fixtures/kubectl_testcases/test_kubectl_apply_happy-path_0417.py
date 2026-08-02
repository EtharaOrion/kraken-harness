def test_apply_service_0417_creates_alt(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: azse-0417\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "azse-0417" in result.stdout
