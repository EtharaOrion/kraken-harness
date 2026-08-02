def test_apply_ingress_0087_output_yaml(cli, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n  name: aoin-0087\n  namespace: default\nspec:\n  rules:\n  - host: example.local\n    http:\n      paths:\n      - path: /\n        pathType: Prefix\n        backend:\n          service:\n            name: demo\n            port: {number: 80}\n')
    result = cli("apply", "-f", str(manifest), "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert "aoin-0087" in result.stdout
