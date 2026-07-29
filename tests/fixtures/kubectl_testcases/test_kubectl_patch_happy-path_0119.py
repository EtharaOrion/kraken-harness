def test_patch_service_0119_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: pise-0119\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "service", "pise-0119", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x119"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "service", "pise-0119", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x119"}}}')
    assert r2.returncode == 0, r2.stderr
