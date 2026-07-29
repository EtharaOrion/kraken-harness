def test_get_service_0034_output_yaml(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: gfse-0034\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "service", "gfse-0034", "-n", "default", "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
