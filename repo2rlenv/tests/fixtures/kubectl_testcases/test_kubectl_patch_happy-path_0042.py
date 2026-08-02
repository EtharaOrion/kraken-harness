def test_patch_ingress_0042_strategic(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n  name: pin-0042\n  namespace: default\nspec:\n  rules:\n  - host: example.local\n    http:\n      paths:\n      - path: /\n        pathType: Prefix\n        backend:\n          service:\n            name: demo\n            port: {number: 80}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "ingress", "pin-0042", "-n", "default", "-p", '{"metadata":{"labels":{"lane":"a42"}}}')
    assert result.returncode == 0, result.stderr
    assert "pin-0042" in result.stdout
