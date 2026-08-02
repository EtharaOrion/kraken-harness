def test_apply_service_0028_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: aise-0028\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    r1 = cli("apply", "-f", str(manifest))
    assert r1.returncode == 0, r1.stderr
    r2 = cli("apply", "-f", str(manifest))
    assert r2.returncode == 0, r2.stderr
