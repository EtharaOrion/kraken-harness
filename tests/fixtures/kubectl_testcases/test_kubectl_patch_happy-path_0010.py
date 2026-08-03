def test_patch_service_0010_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: pse-0010\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "service", "pse-0010", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b10"}}}')
    assert result.returncode == 0, result.stderr
    assert "pse-0010" in result.stdout
