def test_patch_ingress_0322_idempotent(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n  name: piin-0322\n  namespace: default\nspec:\n  rules:\n  - host: example.local\n    http:\n      paths:\n      - path: /\n        pathType: Prefix\n        backend:\n          service:\n            name: demo\n            port: {number: 80}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    r1 = cli("patch", "ingress", "piin-0322", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x322"}}}')
    assert r1.returncode == 0, r1.stderr
    r2 = cli("patch", "ingress", "piin-0322", "-n", "default", "-p", '{"metadata":{"labels":{"stage":"x322"}}}')
    assert r2.returncode == 0, r2.stderr
