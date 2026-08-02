def test_describe_service_0237_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: esse-0237\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "service", "esse-0237", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esse-0237" in result.stdout
