def test_patch_ingress_0043_merge(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n  name: pin-0043\n  namespace: default\nspec:\n  rules:\n  - host: example.local\n    http:\n      paths:\n      - path: /\n        pathType: Prefix\n        backend:\n          service:\n            name: demo\n            port: {number: 80}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "ingress", "pin-0043", "-n", "default", "--type=merge", "-p", '{"metadata":{"labels":{"lane":"b43"}}}')
    assert result.returncode == 0, result.stderr
    assert "pin-0043" in result.stdout
